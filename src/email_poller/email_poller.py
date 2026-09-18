import os
import re
import time
import json
import asyncio
import imaplib
import smtplib

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from email.message import EmailMessage

from openai import OpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ============================================================
# Environment variables
# ============================================================

# ------------------------------------------------------------
# IMAP
# ------------------------------------------------------------

IMAP_HOST = os.environ["IMAP_HOST"]
IMAP_USER = os.environ["IMAP_USER"]


# ------------------------------------------------------------
# SMTP
# ------------------------------------------------------------

SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ["SMTP_USER"]


# ------------------------------------------------------------
# Mailboxes
# ------------------------------------------------------------

HELPDESK_MAILBOX = os.environ["HELPDESK_MAILBOX"]


# ------------------------------------------------------------
# Yandex AI Studio
# ------------------------------------------------------------

# Example:
#
# gpt://b1xxxxxxxxxxxxxxxxxxxx/yandexgpt/latest
#
# b1xxxxxxxxxxxxxxxxxxxx = Yandex Cloud folder ID
#
MODEL_URI = os.environ["MODEL_URI"]


# ------------------------------------------------------------
# MCP Gateway (ydb-tickets)
# ------------------------------------------------------------

# URL шлюза, полученный через:
#   yc serverless mcp-gateway get ydb-tickets-mcp
#
MCP_GATEWAY_URL = os.environ["MCP_GATEWAY_URL"]

# Yandex Cloud folder ID (нужен для параметра project в OpenAI-клиенте)
FOLDER_ID = os.environ["FOLDER_ID"]

# Yandex AI Studio search index (RAG knowledge base).
# Created with: scripts\deploy_kb_index.ps1
SEARCH_INDEX_ID = os.environ["SEARCH_INDEX_ID"]


# ------------------------------------------------------------
# Secrets
# ------------------------------------------------------------

# Password for IMAP/SMTP
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

# API key for Yandex AI Studio
API_KEY = os.environ["API_KEY"]


# ============================================================
# IMAP helpers
# ============================================================

def _imap_mark_seen(imap, num):
    """
    Mark email as read.

    The email is marked as Seen only after successful
    processing and sending of the reply.
    """

    status, _ = imap.store(
        num,
        "+FLAGS",
        "\\Seen"
    )

    if status != "OK":
        raise RuntimeError(
            f"Cannot mark message {num!r} as Seen"
        )


def _get_email_body(msg):
    """
    Get text/plain body.

    If text/plain does not exist, use HTML as fallback.
    """

    # --------------------------------------------------------
    # Preferred: text/plain
    # --------------------------------------------------------

    body_part = msg.get_body(
        preferencelist=("plain",)
    )

    if body_part is not None:

        return body_part.get_content().strip()


    # --------------------------------------------------------
    # Fallback: text/html
    # --------------------------------------------------------

    html_part = msg.get_body(
        preferencelist=("html",)
    )

    if html_part is not None:

        html = html_part.get_content()

        # Basic HTML -> text conversion.
        # No external package required.

        text = re.sub(
            r"<br\s*/?>",
            "\n",
            html,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"</p\s*>",
            "\n",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"<[^>]+>",
            "",
            text
        )

        return text.strip()


    return ""


# ============================================================
# MCP Gateway — direct tool call (bypassing the LLM)
#
# Used to record model/tokens/latency into `messages` after the
# model has already answered — this data is only known to this
# Python code (from the Responses API result), not to the model
# itself, so it cannot be filled in correctly if the *model*
# is the one calling append-message.
# ============================================================

_METADATA_TOKEN_URL = (
    "http://169.254.169.254/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)


def _get_iam_token():
    """
    Fetch a short-lived IAM token for the service account attached
    to this Cloud Function, via the instance metadata service.
    No secret needs to be stored for this — it works the same way
    as ydb.iam.MetadataUrlCredentials() does for the ydb-tickets
    function, just over plain HTTP here.
    """

    import urllib.request

    request = urllib.request.Request(
        _METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
    )

    with urllib.request.urlopen(request, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data["access_token"]


async def _call_mcp_tool_async(tool_name, arguments):
    iam_token = _get_iam_token()

    headers = {"Authorization": f"Bearer {iam_token}"}

    async with streamablehttp_client(
        MCP_GATEWAY_URL,
        headers=headers,
    ) as (read_stream, write_stream, _):

        async with ClientSession(read_stream, write_stream) as session:

            await session.initialize()

            result = await session.call_tool(
                tool_name,
                arguments=arguments,
            )

            return result


def call_mcp_tool(tool_name, arguments):
    """
    Synchronous wrapper: Cloud Function handler is sync code,
    the mcp package is async-only, so we run one short-lived
    event loop per call.
    """

    return asyncio.run(
        _call_mcp_tool_async(tool_name, arguments)
    )


def _extract_ticket_id(response):
    """
    Look through the Responses API output for an mcp_call to
    create-ticket and pull ticket_id out of its result, so we
    know which ticket to attach the agent's message to.

    Returns None if no ticket was created in this response
    (e.g. the model answered from the prompt alone).
    """

    for item in getattr(response, "output", []) or []:

        if getattr(item, "type", None) != "mcp_call":
            continue

        if getattr(item, "name", None) != "create-ticket":
            continue

        raw_output = getattr(item, "output", None)

        if raw_output is None:
            continue

        try:
            parsed = (
                json.loads(raw_output)
                if isinstance(raw_output, str)
                else raw_output
            )
        except (TypeError, ValueError):
            continue

        ticket_id = parsed.get("ticket_id")

        if ticket_id:
            return ticket_id

    return None


def log_user_message(ticket_id, text):
    """
    Record the customer's exact incoming email text into the
    `messages` table (role=user), via append-message.

    create-ticket already inserts a role=user row itself, but
    with whatever text the model passed as the `text` argument —
    which may be a paraphrase, not the verbatim email. This call
    guarantees an exact copy of what the customer actually wrote
    is also on record, tied to the same ticket_id.
    """

    if not ticket_id:
        return

    try:
        result = call_mcp_tool(
            "append-message",
            {
                "ticket_id": ticket_id,
                "role": "user",
                "text": text,
            },
        )

        print(f"append-message (user, verbatim) result: {result!r}")

    except Exception as exc:
        print(f"WARNING: append-message (user) failed: {exc}")


def log_agent_message(ticket_id, text, model, tokens_in, tokens_out, latency_ms):
    """
    Record the agent's reply into the `messages` table via the
    real append-message MCP tool, with accurate model/usage/
    latency values taken from the Responses API result.
    """

    if not ticket_id:
        print(
            "No ticket_id in this response — nothing to attach "
            "the agent message to, skipping append-message."
        )
        return

    try:
        result = call_mcp_tool(
            "append-message",
            {
                "ticket_id": ticket_id,
                "role": "agent",
                "text": text,
                "model": model or "",
                "tokens_in": tokens_in or 0,
                "tokens_out": tokens_out or 0,
                "latency_ms": latency_ms or 0,
            },
        )

        print(f"append-message result: {result!r}")

    except Exception as exc:
        # Logging the message is best-effort bookkeeping — it
        # must never break email delivery to the customer.
        print(f"WARNING: append-message failed: {exc}")


# ============================================================
# Yandex AI Studio
# ============================================================

def call_yandex_gpt(sender_email, email_text):
    """
    Send the incoming email to a Yandex AI Studio model using
    the OpenAI-compatible Responses API.

    The model is given access to the ydb-tickets MCP server
    (create-ticket / list-my-tickets / append-message), so it
    can create a ticket itself when it cannot answer the
    question from the prompt alone.

    Returns (answer_text, ticket_id, model_name, tokens_in,
    tokens_out, latency_ms) so the caller can separately log
    the agent's message with accurate telemetry.
    """

    print(
        "Creating Yandex AI Studio client..."
    )

    client = OpenAI(
        api_key=API_KEY,
        base_url="https://rest-assistant.api.cloud.yandex.net/v1",
        project=FOLDER_ID,
    )


    # --------------------------------------------------------
    # Prompt
    # --------------------------------------------------------

    prompt = f"""
Ты — оператор службы поддержки.

Твоя задача — подготовить ответ на входящее письмо
клиента.

У тебя есть доступ к базе знаний компании (поиск по документам
HR/IT/администрирования) — используй её, чтобы отвечать точно и
по существующим регламентам, а не по общим знаниям.

В твоём распоряжении есть инструменты ydb_tickets:
- create-ticket — создать тикет, если готового ответа нет;
- list-my-tickets — посмотреть тикеты пользователя по его email;
- append-message — дописать сообщение в историю существующего тикета.

Правила:

1. Отвечай на русском языке.
2. Отвечай вежливо и профессионально.
3. Отвечай непосредственно на вопрос клиента.
4. Не выдумывай информацию, которой нет в письме и нет в базе знаний.
5. Сначала ищи ответ в базе знаний. Если там есть точный ответ на
   вопрос клиента — отвечай на его основе, тикет не создавай.
6. Если клиент прямо просит завести тикет/заявку/обращение
   (например: "заведи заявку", "оформи обращение", "создай тикет") —
   создавай тикет через create-ticket СРАЗУ, не задавая уточняющих
   вопросов, даже если в базе знаний есть общая информация по теме.
   Категорию (bug | docs | feature | access) выбирай по смыслу
   письма самостоятельно, не спрашивая клиента.
7. Если клиент не просил тикет явно, но ответа нет ни в письме, ни
   в базе знаний, и у тебя достаточно данных, чтобы завести
   осмысленный тикет — создай тикет через create-ticket и сообщи
   клиенту номер.
8. Уточняющий вопрос вместо тикета — это крайний случай: используй
   его, только если ты не можешь понять, о чём вообще просьба, а не
   просто чтобы собрать больше деталей "на всякий случай".
9. Во всех случаях создания тикета: user_id — email отправителя
   (см. ниже), затем сообщи клиенту номер тикета (ticket_id) в ответе.
10. Не упоминай, что ответ был создан искусственным интеллектом.
11. Не добавляй тему письма.
12. Верни только готовый текст ответа клиенту.

Email отправителя:
{sender_email}

Текст письма:
{email_text}
""".strip()


    print(
        f"Calling Yandex AI Studio model: {MODEL_URI}"
    )


    # --------------------------------------------------------
    # Call model with the ydb-tickets MCP server attached
    # --------------------------------------------------------

    start_time = time.perf_counter()

    response = client.responses.create(
        model=MODEL_URI,
        input=prompt,
        tools=[
            {
                "type": "file_search",
                "vector_store_ids": [SEARCH_INDEX_ID],
                "max_num_results": 3,
            },
            {
                "type": "mcp",
                "server_label": "ydb_tickets",
                "server_url": MCP_GATEWAY_URL,
                "require_approval": "never",
                "metadata": {
                    "description": (
                        "Создание и просмотр тикетов службы поддержки, "
                        "запись истории переписки по обращению"
                    )
                },
            }
        ],
    )

    latency_ms = int((time.perf_counter() - start_time) * 1000)


    # --------------------------------------------------------
    # Debug: log what the model actually returned, including
    # any MCP tool calls, before extracting the final text.
    # Useful for diagnosing "unknown action" / empty-answer
    # issues on the ydb-tickets side.
    # --------------------------------------------------------

    print(
        f"Response output (debug): {response.output!r}"
    )


    # --------------------------------------------------------
    # Get answer
    # --------------------------------------------------------

    answer = response.output_text


    if not answer or not answer.strip():

        raise RuntimeError(
            "Yandex AI Studio returned empty response"
        )


    answer = answer.strip()


    print(
        f"YandexGPT response length: "
        f"{len(answer)} characters"
    )


    # --------------------------------------------------------
    # Telemetry for messages.append-message: model name, token
    # usage and latency, plus the ticket_id if the model created
    # one during this call.
    # --------------------------------------------------------

    ticket_id = _extract_ticket_id(response)

    model_name = getattr(response, "model", None) or MODEL_URI

    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "input_tokens", 0) if usage else 0
    tokens_out = getattr(usage, "output_tokens", 0) if usage else 0

    return answer, ticket_id, model_name, tokens_in, tokens_out, latency_ms


# ============================================================
# SMTP
# ============================================================

def send_reply(to_email, original_subject, answer):
    """
    Send the generated answer to the original sender.
    """

    message = EmailMessage()


    # --------------------------------------------------------
    # Headers
    # --------------------------------------------------------

    message["From"] = HELPDESK_MAILBOX

    message["To"] = to_email


    # --------------------------------------------------------
    # Subject
    # --------------------------------------------------------

    if original_subject:

        if original_subject.lower().startswith("re:"):

            message["Subject"] = original_subject

        else:

            message["Subject"] = (
                f"Re: {original_subject}"
            )

    else:

        message["Subject"] = (
            "Ответ на ваше обращение"
        )


    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    message.set_content(answer)


    # --------------------------------------------------------
    # SMTP connection
    # --------------------------------------------------------

    print(
        f"Connecting to SMTP "
        f"{SMTP_HOST}:{SMTP_PORT}"
    )


    with smtplib.SMTP_SSL(
        SMTP_HOST,
        SMTP_PORT,
        timeout=30
    ) as smtp:

        print(
            f"Logging into SMTP as {SMTP_USER}"
        )

        smtp.login(
            SMTP_USER,
            EMAIL_PASSWORD
        )


        print(
            f"Sending email to {to_email}"
        )


        smtp.send_message(
            message
        )


    print(
        "SMTP reply sent successfully"
    )


# ============================================================
# Process one email
# ============================================================

def process_email(imap, num):
    """
    Process a single unread email.

    Returns True if processing was successful.

    Important:
    The message is marked Seen only after the reply
    has been successfully sent.
    """

    print(
        f"Processing message {num!r}"
    )


    # --------------------------------------------------------
    # Fetch email
    # --------------------------------------------------------

    status, msg_data = imap.fetch(
        num,
        "(RFC822)"
    )


    if status != "OK":

        raise RuntimeError(
            f"Cannot fetch email {num!r}"
        )


    raw_email = None


    for part in msg_data:

        if (
            isinstance(part, tuple)
            and len(part) == 2
        ):

            raw_email = part[1]

            break


    if raw_email is None:

        raise RuntimeError(
            f"Empty email data for {num!r}"
        )


    # --------------------------------------------------------
    # Parse email
    # --------------------------------------------------------

    msg = BytesParser(
        policy=policy.default
    ).parsebytes(raw_email)


    # --------------------------------------------------------
    # From
    # --------------------------------------------------------

    from_header = msg.get(
        "From",
        ""
    )


    sender_name, sender_email = parseaddr(
        from_header
    )


    if not sender_email:

        raise RuntimeError(
            "Cannot determine sender: "
            f"{from_header!r}"
        )


    print(
        f"Sender: {sender_email}"
    )


    if sender_name:

        print(
            f"Sender name: {sender_name}"
        )


    # --------------------------------------------------------
    # Subject
    # --------------------------------------------------------

    subject = msg.get(
        "Subject",
        ""
    )


    print(
        f"Subject: {subject!r}"
    )


    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    email_text = _get_email_body(
        msg
    )


    if not email_text:

        email_text = (
            "(Письмо не содержит текста.)"
        )


    print(
        "Email body length: "
        f"{len(email_text)} characters"
    )


    # --------------------------------------------------------
    # Call YandexGPT
    # --------------------------------------------------------

    (
        answer,
        ticket_id,
        model_name,
        tokens_in,
        tokens_out,
        latency_ms,
    ) = call_yandex_gpt(
        sender_email,
        email_text
    )


    print(
        "YandexGPT response received "
        f"(ticket_id={ticket_id!r}, model={model_name!r}, "
        f"tokens_in={tokens_in}, tokens_out={tokens_out}, "
        f"latency_ms={latency_ms})"
    )


    # --------------------------------------------------------
    # Record both replicas of this cycle:
    #   1. the customer's verbatim email (role=user)
    #   2. the agent's reply, with accurate telemetry (role=agent)
    #
    # Both only make sense once a ticket exists — messages.ticket_id
    # is required by schema, and if create-ticket wasn't called in
    # this response there is nothing to attach a message to yet.
    # --------------------------------------------------------

    log_user_message(
        ticket_id,
        email_text,
    )

    log_agent_message(
        ticket_id,
        answer,
        model_name,
        tokens_in,
        tokens_out,
        latency_ms,
    )


    # --------------------------------------------------------
    # Send SMTP reply
    # --------------------------------------------------------

    send_reply(
        sender_email,
        subject,
        answer
    )


    # --------------------------------------------------------
    # IMPORTANT
    #
    # Mark as Seen ONLY after successful SMTP sending.
    # --------------------------------------------------------

    _imap_mark_seen(
        imap,
        num
    )


    print(
        f"Message {num!r} marked as Seen"
    )


    return True


# ============================================================
# Cloud Function
# ============================================================

def handler(event, context):

    imap = None

    processed = 0
    errors = 0
    found = 0


    try:

        # ====================================================
        # 1. Connect to IMAP
        # ====================================================

        print(
            f"Connecting to IMAP {IMAP_HOST}:993"
        )


        imap = imaplib.IMAP4_SSL(
            IMAP_HOST,
            993
        )


        # ====================================================
        # 2. Login
        # ====================================================

        print(
            f"Logging into IMAP as {IMAP_USER}"
        )


        imap.login(
            IMAP_USER,
            EMAIL_PASSWORD
        )


        print(
            "IMAP login successful"
        )


        # ====================================================
        # 3. Select INBOX
        # ====================================================

        status, _ = imap.select(
            "INBOX"
        )


        if status != "OK":

            raise RuntimeError(
                "Cannot select INBOX"
            )


        print(
            "INBOX selected"
        )


        # ====================================================
        # 4. Find unread emails
        # ====================================================

        status, data = imap.search(
            None,
            "UNSEEN"
        )


        if status != "OK":

            raise RuntimeError(
                "IMAP search UNSEEN failed"
            )


        message_numbers = data[0].split()


        found = len(
            message_numbers
        )


        print(
            f"Found {found} unread email(s)"
        )


        # ====================================================
        # 5. Process every email
        # ====================================================

        for num in message_numbers:

            try:

                process_email(
                    imap,
                    num
                )


                processed += 1


                print(
                    f"Message {num!r} "
                    "processed successfully"
                )


            except Exception as exc:

                errors += 1


                print(
                    f"ERROR processing message "
                    f"{num!r}: {exc}"
                )


                # IMPORTANT:
                #
                # Do NOT mark the email as Seen here.
                #
                # It remains UNSEEN and will be retried
                # on the next Timer invocation.


                print(
                    f"Message {num!r} "
                    "remains UNSEEN and will be retried"
                )


        # ====================================================
        # 6. Function result
        # ====================================================

        result = {
            "status": "ok",
            "found": found,
            "processed": processed,
            "errors": errors,
        }


        print(
            f"Finished: {result}"
        )


        return result


    finally:

        # ====================================================
        # Close IMAP connection
        # ====================================================

        if imap is not None:

            try:

                imap.close()

            except Exception:

                pass


            try:

                imap.logout()

            except Exception:

                pass
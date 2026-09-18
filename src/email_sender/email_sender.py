import json
import os
import smtplib

from email.message import EmailMessage


# ============================================================
# Environment variables
# ============================================================

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

# Адрес оператора функция берёт из своего окружения, а не из тела
# запроса — это не придирка к стилю. httpCall в YaWL не шлёт IAM-токен,
# поэтому функцию приходится открывать без аутентификации (allow-
# unauthenticated-invoke) — значит дёрнуть её может любой, кто узнал
# URL. Если бы адресат приходил в теле запроса, это была бы открытая
# рассылка с корпоративного ящика на любой адрес; с адресатом из
# окружения худшее, что можно получить, — лишний дайджест оператору.
OPERATOR_EMAIL = os.environ["OPERATOR_EMAIL"]


# ------------------------------------------------------------
# Secrets
# ------------------------------------------------------------

# Тот же Lockbox-секрет email-credentials, что использует email-poller
# для IMAP/SMTP (ключ password).
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]


# ============================================================
# HTTP helpers
# ============================================================

def _http(status_code, body):
    """
    httpCall в src/workflow.yaml ожидает обычный HTTP-ответ Cloud
    Function (statusCode/headers/body), а не «сырой» словарь.
    """

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(
            body,
            ensure_ascii=False
        ),
    }


def _parse_body(event):
    """
    httpCall шлёт JSON-тело обычным POST-запросом — event приходит в
    том же формате, что и от HTTP-триггера Cloud Function: тело лежит
    в event["body"] строкой (или уже разобранным словарём/списком).
    """

    raw = event.get("body", "") if isinstance(event, dict) else event

    if not raw:
        return {}

    if isinstance(raw, (dict, list)):
        return raw

    return json.loads(raw)


# ============================================================
# SMTP
# ============================================================

def _send_digest(subject, body):
    """
    Отправить письмо-дайджест оператору. Адресат всегда OPERATOR_EMAIL
    из окружения функции, тело/тема — то, что передал workflow.
    """

    message = EmailMessage()

    message["From"] = HELPDESK_MAILBOX
    message["To"] = OPERATOR_EMAIL
    message["Subject"] = subject or "Дайджест просроченных тикетов"

    message.set_content(body or "")

    print(
        f"Connecting to SMTP {SMTP_HOST}:{SMTP_PORT}"
    )

    with smtplib.SMTP_SSL(
        SMTP_HOST,
        SMTP_PORT,
        timeout=30
    ) as smtp:

        smtp.login(
            SMTP_USER,
            EMAIL_PASSWORD
        )

        print(
            f"Sending digest to operator {OPERATOR_EMAIL}"
        )

        smtp.send_message(
            message
        )

    print(
        "SMTP digest sent successfully"
    )


# ============================================================
# Cloud Function
#
# SMTP-обёртка для шага httpCall в src/workflow.yaml (шаг 9,
# daily-escalation). YaWL не умеет отправлять почту напрямую, поэтому
# workflow делает обычный HTTP POST сюда с телом {"subject", "body"}.
# ============================================================

def handler(event, context):

    try:

        data = _parse_body(event)

        subject = data.get("subject") or "Дайджест просроченных тикетов"
        body = data.get("body")

        if body is None:
            # На случай если workflow пришлёт тело в другой форме —
            # шлём не пустое письмо, а то, что реально получили.
            body = json.dumps(data, ensure_ascii=False)

        _send_digest(
            subject,
            str(body)
        )

        return _http(
            200,
            {"status": "ok"}
        )

    except Exception as exc:

        print(
            f"ERROR sending digest: {exc}"
        )

        return _http(
            500,
            {"status": "error", "message": str(exc)}
        )

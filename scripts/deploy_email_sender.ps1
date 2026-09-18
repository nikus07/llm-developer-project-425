# ЗАПУСКАТЬ ИЗ КОРНЯ ПРОЕКТА .\scripts\deploy_email_sender.ps1
# ============================================
# Deploy email-sender Cloud Function (шаг 9)
#
# HTTP-обёртка над SMTP для шага httpCall в src\workflow.yaml — YaWL не
# умеет отправлять почту напрямую. Функция публичная: httpCall не шлёт
# IAM-токен, поэтому после деплоя нужно один раз выполнить
# allow-unauthenticated-invoke (шаг 2 ниже, скрипт делает это сам).
# ============================================

$FUNCTION_NAME = "email-sender"
$RUNTIME       = "python312"
$ENTRYPOINT    = "email_sender.handler"    # matches "def handler(...)" in email_sender.py
$MEMORY        = "128m"
$TIMEOUT       = "30s"
$SOURCE_PATH   = "src\email_sender"

# Тот же SA, что и у остальных функций проекта.
$SA_ID = "aje1suvv5as4qndn7ktk"

# Те же почтовые реквизиты, что и у email-poller (scripts\deploy_poller.ps1)
$SMTP_HOST        = "smtp.yandex.ru"
$SMTP_PORT        = "465"
$SMTP_USER        = "kir.nv.123@yandex.ru"
$HELPDESK_MAILBOX = "kir.nv.123@yandex.ru"

# Адрес оператора — единственное принципиально новое значение для этого
# шага. Дайджест всегда уходит именно сюда, что бы ни пришло в теле запроса.
$OPERATOR_EMAIL = "nikus_07@bk.ru"   # TODO: подставьте реальный адрес оператора

$ENVIRONMENT = "SMTP_HOST=$SMTP_HOST,SMTP_PORT=$SMTP_PORT,SMTP_USER=$SMTP_USER,HELPDESK_MAILBOX=$HELPDESK_MAILBOX,OPERATOR_EMAIL=$OPERATOR_EMAIL"


# --------------------------------------------
# 0. Создать саму функцию, если её ещё нет (version create требует уже
#    существующую функцию — в отличие от ydb-tickets/email-poller, для
#    email-sender это первый деплой). Идемпотентно: на повторных запусках
#    просто пропускается.
# --------------------------------------------

yc serverless function get --name $FUNCTION_NAME 2>$null | Out-Null

if ($LASTEXITCODE -ne 0) {

    Write-Host "Function $FUNCTION_NAME does not exist yet, creating..."

    yc serverless function create --name $FUNCTION_NAME

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Function create failed! Exit code: $LASTEXITCODE"
        exit $LASTEXITCODE
    }
}


# --------------------------------------------
# 1. Деплой версии функции
# --------------------------------------------

Write-Host "Creating new function version..."

yc serverless function version create `
    --function-name $FUNCTION_NAME `
    --runtime $RUNTIME `
    --entrypoint $ENTRYPOINT `
    --memory $MEMORY `
    --execution-timeout $TIMEOUT `
    --source-path $SOURCE_PATH `
    --service-account-id $SA_ID `
    --environment $ENVIRONMENT `
    --secret environment-variable=EMAIL_PASSWORD,name=email-credentials,key=password

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Deployment failed!"
    Write-Host "Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Deployment successful!"


# --------------------------------------------
# 2. Открыть функцию без аутентификации — httpCall в YaWL не умеет
#    передавать IAM-токен. Команда идемпотентна, безопасно запускать
#    повторно при каждом деплое.
# --------------------------------------------

Write-Host ""
Write-Host "Allowing unauthenticated invoke..."

yc serverless function allow-unauthenticated-invoke --name $FUNCTION_NAME

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "allow-unauthenticated-invoke failed!"
    Write-Host "Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done. Get the public URL with:"
Write-Host "  yc serverless function get $FUNCTION_NAME"
Write-Host "and paste it into the 'url' field of the send_digest step in src\workflow.yaml"

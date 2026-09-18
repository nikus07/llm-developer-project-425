# ЗАПУСКАТЬ ИЗ КОРНЯ ПРОЕКТА .\scripts\deploy_workflow.ps1
# ============================================
# Deploy daily-escalation workflow (шаг 9)
#
# Перед первым запуском:
#   1. Создайте промпт-шаблон/агента в AI Studio Agent Atelier и подставьте
#      его id в поле promptTemplateId шага build_digest (src\workflow.yaml).
#   2. Задеплойте email-sender (.\scripts\deploy_email_sender.ps1) и
#      подставьте её публичный URL в поле url шага send_digest.
#   3. По желанию — проверьте src\workflow.yaml по JSON-схеме YaWL перед
#      деплоем (ссылка в README).
# ============================================

$WORKFLOW_NAME = "daily-escalation"
$YAML_SPEC     = "src\workflow.yaml"
$SA_ID         = "aje1suvv5as4qndn7ktk"
$FOLDER_ID     = "b1gub2v21kgnvqvtbj19"


# --------------------------------------------
# 1. Роли SA, нужные шагам workflow.
#    ydb.editor и ai.languageModels.user у ai-studio-sa уже есть (см.
#    README) — команда идемпотентна, повторный add-access-binding не
#    навредит. ai.assistants.editor — новая роль: без неё aiStudioAgent
#    падает с 403 Forbidden на https://ai.api.cloud.yandex.net/v1/responses.
# --------------------------------------------

Write-Host "Granting SA roles..."

foreach ($ROLE in @("ydb.editor", "ai.assistants.editor", "ai.languageModels.user")) {
    yc resource-manager folder add-access-binding `
        --id $FOLDER_ID `
        --service-account-id $SA_ID `
        --role $ROLE
}


# --------------------------------------------
# 2. Создать (первый раз) или обновить workflow.
#    Это НЕ --file workflow.yaml и НЕ deploy-revision — именно
#    --yaml-spec, формат YaWL 0.1.
# --------------------------------------------

yc serverless workflow get --name $WORKFLOW_NAME 2>$null | Out-Null
$workflowExists = ($LASTEXITCODE -eq 0)

if ($workflowExists) {

    Write-Host "Updating existing workflow $WORKFLOW_NAME ..."

    # --schedule-timezone Europe/Moscow даёт "ERROR: Invalid timezone" на
    # некоторых сборках yc CLI под Windows (нет IANA tzdata на машине —
    # это баг окружения, а не опечатка в имени зоны). Обходим без флага:
    # cron без --schedule-timezone выполняется в UTC, а Москва — всегда
    # UTC+3 без перехода на летнее/зимнее время, поэтому 09:00 МСК = 06:00
    # UTC постоянно, без сезонных сюрпризов.
    #
    # "?" в поле day-of-week (как в шпаргалке про формат cron и в
    # deploy_trg.ps1 для триггера) здесь НЕ принимается — это другой
    # парсер (workflow-scheduler, не trigger): "Invalid expression: ?".
    # Используем "*" в dow вместо "?" — при "*" в обоих dom/dow это
    # значит "без ограничения по дню", т.е. каждый день.
    yc serverless workflow update `
        --name $WORKFLOW_NAME `
        --yaml-spec $YAML_SPEC `
        --schedule-cron-expression "0 6 * * * *"
}
else {

    Write-Host "Creating workflow $WORKFLOW_NAME ..."

    yc serverless workflow create `
        --name $WORKFLOW_NAME `
        --yaml-spec $YAML_SPEC `
        --service-account-id $SA_ID

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Create failed! Exit code: $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    Write-Host "Setting schedule (cron 06:00 UTC = 09:00 Europe/Moscow)..."

    # Без --schedule-timezone и без "?" в dow — см. комментарий в ветке
    # update выше (обе особенности этого workflow-scheduler'а).
    yc serverless workflow update `
        --name $WORKFLOW_NAME `
        --yaml-spec $YAML_SPEC `
        --schedule-cron-expression "0 6 * * * *"
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed! Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}


# --------------------------------------------
# 3. scheduled-trigger запускает workflow от имени своего SA (у нас — тот
#    же ai-studio-sa, что и у самого workflow). Ему всё равно нужны обе
#    роли НА САМОМ workflow (не на каталоге!):
#      нет executor -> "service account does not have rights to start
#                        the workflow" / 400 can't invoke workflow
#      нет viewer    -> 400 doesn't have get permission for workflow
#                        (API делает GET перед запуском)
#    yc serverless workflow allow-unauthenticated-execution существует,
#    но не сохраняется в текущем YC — не полагайтесь на него.
# --------------------------------------------

Write-Host ""
Write-Host "Granting workflow access bindings to SA..."

yc serverless workflow add-access-binding `
    --name $WORKFLOW_NAME `
    --role serverless.workflows.executor `
    --service-account-id $SA_ID

yc serverless workflow add-access-binding `
    --name $WORKFLOW_NAME `
    --role serverless.workflows.viewer `
    --service-account-id $SA_ID

Write-Host ""
Write-Host "Done. Verify with:"
Write-Host "  yc serverless workflow list-access-bindings --name $WORKFLOW_NAME"
Write-Host ""
Write-Host "Manual test before relying on the schedule:"
Write-Host "  yc serverless workflow execution start $WORKFLOW_NAME"
Write-Host "  yc serverless workflow execution get <execution-id>"

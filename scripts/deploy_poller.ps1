# ============================================
# Deploy email-poller Cloud Function
# ============================================

$FUNCTION_NAME = "email-poller"
$RUNTIME = "python312"
$ENTRYPOINT = "email_poller.handler"
$MEMORY = "256m"
$TIMEOUT = "120s"
$SOURCE_PATH = "src\email_poller"

# Service account ID
$SA_ID = "aje1suvv5as4qndn7ktk"

# Yandex Cloud folder ID
$FOLDER_ID = "b1gub2v21kgnvqvtbj19"

$MODEL_URI = "gpt://b1gub2v21kgnvqvtbj19/yandexgpt/latest"

# URL of the ydb-tickets MCP Gateway.
# Get it with: yc serverless mcp-gateway get ydb-tickets-mcp
$MCP_GATEWAY_URL = "https://db83n9dnnnc1hu2flofo.5p9km096.mcpgw.serverless.yandexcloud.net"

# Yandex AI Studio search index (RAG knowledge base).
# Created with: scripts\deploy_kb_index.ps1
$SEARCH_INDEX_ID = "fvtr3gkl43m96c4ii65b"


# Environment variables
$ENVIRONMENT = "IMAP_HOST=imap.yandex.ru,IMAP_USER=kir.nv.123@yandex.ru,SMTP_HOST=smtp.yandex.ru,SMTP_PORT=465,SMTP_USER=kir.nv.123@yandex.ru,HELPDESK_MAILBOX=kir.nv.123@yandex.ru,MODEL_URI=$MODEL_URI,MCP_GATEWAY_URL=$MCP_GATEWAY_URL,FOLDER_ID=$FOLDER_ID,SEARCH_INDEX_ID=$SEARCH_INDEX_ID"


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
    --secret environment-variable=EMAIL_PASSWORD,name=email-credentials,key=password `
    --secret environment-variable=API_KEY,name=ai-studio-api-key,key=value

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Deployment successful!"
}
else {
    Write-Host ""
    Write-Host "Deployment failed!"
    Write-Host "Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

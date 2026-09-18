# ЗАПУСКАТЬ ИЗ КОРНЯ ПРОЕКТА .\scripts\deploy_ydb_tickets.ps1
# ============================================
# Deploy ydb-tickets Cloud Function
# ============================================

$FUNCTION_NAME = "ydb-tickets"
$RUNTIME       = "python312"
$ENTRYPOINT    = "index.handler"     # matches "def handler(...)" in index.py
$MEMORY        = "256m"
$TIMEOUT       = "30s"

$SRC_DIR  = "src\ydb_tickets"
$TMP_DIR  = "tmp"
$ZIP_PATH = Join-Path $TMP_DIR "ydb-tickets.zip"

$SA_ID = "aje1suvv5as4qndn7ktk"  # service account with the ydb.editor role on your database

$YDB_ENDPOINT_VALUE = "grpcs://ydb.serverless.yandexcloud.net:2135"
$YDB_DATABASE_VALUE = "/ru-central1/b1gjgpo4ro5npu1e344j/etn4esadbc57dpkus2n1"

# если функция еще не создана
# yc serverless function create --name ydb-tickets

# --------------------------------------------
# 0. (Run once) Create Lockbox secrets if they
#    do not exist yet. Skip if already created.
# --------------------------------------------

# yc lockbox secret create `
#     --name ydb-endpoint `
#     --payload '[{"key": "value", "text_value": "'"$YDB_ENDPOINT_VALUE"'"}]'
#
# yc lockbox secret create `
#     --name ydb-database `
#     --payload '[{"key": "value", "text_value": "'"$YDB_DATABASE_VALUE"'"}]'
#
# The service account $SA_ID also needs the lockbox.payloadViewer role
# on both secrets, otherwise the function cannot read them at runtime:
#
# yc lockbox secret add-access-binding ydb-endpoint `
#     --role lockbox.payloadViewer `
#     --subject serviceAccount:$SA_ID
#
# yc lockbox secret add-access-binding ydb-database `
#     --role lockbox.payloadViewer `
#     --subject serviceAccount:$SA_ID


# --------------------------------------------
# 1. Build the deployment zip
#    (equivalent of: zip -j ydb-tickets.zip index.py requirements.txt)
# --------------------------------------------

Write-Host "Building $ZIP_PATH ..."

if (-not (Test-Path $TMP_DIR)) {
    New-Item -ItemType Directory -Path $TMP_DIR | Out-Null
}

if (Test-Path $ZIP_PATH) {
    Remove-Item $ZIP_PATH -Force
}

$filesToZip = @(
    (Join-Path $SRC_DIR "index.py"),
    (Join-Path $SRC_DIR "requirements.txt")
)

foreach ($f in $filesToZip) {
    if (-not (Test-Path $f)) {
        Write-Host "Missing file: $f"
        exit 1
    }
}

# Passing explicit file paths (not a folder) makes Compress-Archive
# place them at the root of the zip, with no ydb_tickets/ subfolder
# inside — same effect as "zip -j".
Compress-Archive -Path $filesToZip -DestinationPath $ZIP_PATH -Force

Write-Host "Zip created: $ZIP_PATH"


# --------------------------------------------
# 2. Deploy the function version
# --------------------------------------------

Write-Host ""
Write-Host "Creating new function version..."

yc serverless function version create `
    --function-name $FUNCTION_NAME `
    --runtime $RUNTIME `
    --entrypoint $ENTRYPOINT `
    --memory $MEMORY `
    --execution-timeout $TIMEOUT `
    --source-path $ZIP_PATH `
    --service-account-id $SA_ID `
    --secret environment-variable=YDB_ENDPOINT,name=ydb-endpoint,key=value `
    --secret environment-variable=YDB_DATABASE,name=ydb-database,key=value

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
# ============================================
# Apply schema (tickets, messages) to YDB
# ============================================

# --------------------------------------------
# Settings — change to match your database
# --------------------------------------------

$YC_PATH        = "yc"
$SCHEMA_PATH    = "src\ydb_tickets\schema.sql"
$INIT_SCRIPT    = "scripts\init_schema.py"

$CLOUD_ID = "b1gjgpo4ro5npu1e344j"
$DB_ID    = "etn4esadbc57dpkus2n1"


# --------------------------------------------
# 1. Activate venv
# --------------------------------------------

Write-Host "Activating venv..."

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "venv not found. Creating: python -m venv .venv"
    python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1


# --------------------------------------------
# 2. Set environment variables
# --------------------------------------------

$env:YDB_ENDPOINT = "grpcs://ydb.serverless.yandexcloud.net:2135"
$env:YDB_DATABASE = "/ru-central1/$CLOUD_ID/$DB_ID"

Write-Host "Fetching IAM token via yc..."

$env:YC_IAM_TOKEN = & $YC_PATH iam create-token

if ([string]::IsNullOrWhiteSpace($env:YC_IAM_TOKEN)) {
    Write-Host ""
    Write-Host "Failed to get YC_IAM_TOKEN. Make sure 'yc init' was run and the path to yc.exe is correct."
    exit 1
}


# --------------------------------------------
# 3. Run the schema-apply script
# --------------------------------------------

Write-Host "Endpoint: $env:YDB_ENDPOINT"
Write-Host "Database: $env:YDB_DATABASE"
Write-Host ""
Write-Host "Running $INIT_SCRIPT..."

python $INIT_SCRIPT $SCHEMA_PATH

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Schema applied successfully!"
}
else {
    Write-Host ""
    Write-Host "Schema application failed."
    Write-Host "Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}
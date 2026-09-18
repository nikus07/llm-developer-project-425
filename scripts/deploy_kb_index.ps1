# ЗАПУСКАТЬ ИЗ КОРНЯ ПРОЕКТА .\scripts\deploy_kb_index.ps1
# ============================================
# Create the Yandex AI Studio search index (vector store)
# from the local knowledge base
# ============================================
#
# Перед первым запуском добавьте в .env (он в .gitignore, в git не попадёт)
# строку с вашим API-ключом:
#
#   YC_API_KEY=<ваш ключ>
#
# Значение можно получить из Lockbox: yc lockbox payload get ai-studio-api-key --key value

# 1. Activate venv
. .\.venv\Scripts\Activate.ps1

# 2. Load settings from .env (YC_API_KEY и т.д.) — файл не отслеживается git'ом
$envFile = ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#=\s][^=]*)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

$env:YC_FOLDER_ID = "b1gub2v21kgnvqvtbj19"

if (-not $env:YC_API_KEY) {
    Write-Host "YC_API_KEY не найден в .env."
    Write-Host "Добавьте в .env строку: YC_API_KEY=<ваш ключ>"
    Write-Host "Значение можно получить: yc lockbox payload get ai-studio-api-key --key value"
    exit 1
}

# 3. Create the search index from the local knowledge base
yandex-ai-studio vector-stores local `
    knowledge_base\hr\*.md `
    knowledge_base\it\*.md `
    knowledge_base\admin\*.md `
    --name "help-desk-kb"

# Команда напечатает search_index_id (строка вида "fvt...") —
# скопируйте его и добавьте в .env как SEARCH_INDEX_ID=<id>.

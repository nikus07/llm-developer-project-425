### Hexlet tests and linter status:
[![Actions Status](https://github.com/nikus07/llm-developer-project-425/actions/workflows/hexlet-check.yml/badge.svg)](https://github.com/nikus07/llm-developer-project-425/actions)

### Роли Сервисного Аккаунта (SA)
Для работы проекта сервисному аккаунту `ai-studio-sa` в каталоге назначены следующие роли:
* `functions.functionInvoker` — для вызова Cloud Functions.
* `serverless.mcpGateways.invoker` — для работы со шлюзами MCP.
* `lockbox.payloadViewer` — для чтения секретов из Lockbox.
* `ai.languageModels.user` — для отправки запросов в Yandex AI Studio.
* `ydb.editor` — для управления структурой и данными базы YDB.

### Хранение секретов в Yandex Cloud Lockbox
В сервисе Lockbox созданы три секрета:
1. **`ydb-endpoint`** — содержит gRPC эндпоинт для подключения к базе данных YDB.
2. **`ydb-database`** — содержит полный путь к базе данных YDB в облаке.
3. **`ai-studio-api-key`** — содержит API-ключ для авторизации в Yandex AI Studio при вызовах снаружи облачной инфраструктуры.

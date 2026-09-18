"""
Применяет DDL-файл (schema.sql) к базе YDB Serverless.

Использование:
    export YDB_ENDPOINT=grpcs://ydb.serverless.yandexcloud.net:2135
    export YDB_DATABASE=/ru-central1/<cloud-id>/<db-id>
    export YC_IAM_TOKEN=$(yc iam create-token)
    python scripts/init_schema.py src/ydb_tickets/schema.sql

Логика разбора файла:
    - строки, целиком состоящие из комментария (начинаются с "--"
      после strip()), удаляются;
    - инлайновые комментарии внутри CREATE TABLE (например,
      "id  Utf8,  -- UUID") НЕ трогаются — YQL их прекрасно понимает,
      удалять их не нужно и вредно (можно случайно съесть часть строки);
    - то, что осталось, делится на отдельные statement'ы по ";";
    - каждый statement выполняется отдельным вызовом execute_scheme().
"""

import os
import sys

import ydb


def load_statements(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    kept_lines = []

    for line in raw.splitlines():
        if line.strip().startswith("--"):
            # строка целиком комментарий -> выбрасываем
            continue
        kept_lines.append(line)

    cleaned = "\n".join(kept_lines)

    statements = [
        stmt.strip()
        for stmt in cleaned.split(";")
        if stmt.strip()
    ]

    return statements


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python init_schema.py <path/to/schema.sql>")
        sys.exit(1)

    schema_path = sys.argv[1]

    endpoint = os.environ["YDB_ENDPOINT"]
    database = os.environ["YDB_DATABASE"]
    iam_token = os.environ["YC_IAM_TOKEN"]

    credentials = ydb.AccessTokenCredentials(iam_token)

    driver_config = ydb.DriverConfig(
        endpoint,
        database,
        credentials=credentials,
    )

    statements = load_statements(schema_path)
    print(f"Найдено {len(statements)} statement(ов) в {schema_path}\n")

    with ydb.Driver(driver_config) as driver:
        driver.wait(timeout=10, fail_fast=True)

        with ydb.SessionPool(driver) as pool:
            for i, stmt in enumerate(statements, start=1):
                print(f"[{i}/{len(statements)}] Выполняю:\n{stmt}\n")

                def execute(session, stmt=stmt):
                    session.execute_scheme(stmt)

                pool.retry_operation_sync(execute)
                print(f"[{i}/{len(statements)}] OK\n")

    print("Схема успешно применена.")


if __name__ == "__main__":
    main()

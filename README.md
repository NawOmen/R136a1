# Сборка B2B

Прототип B2B-маркетплейса, создающего коалиции покупателей и производителей и моделирующего устойчивость сделки.

## Статус

- Этап 0: создание репозитория и фиксация архитектуры — выполнено.
- Этап 1: границы MVP, пользовательские сценарии и синтетические данные — выполнено.
- Этап 2: каркас и инфраструктура (монорепозиторий, Docker Compose, Web App, Gateway Auth, Marketplace, PostgreSQL, миграции, CI, проверка Ollama) — выполнено.
- Этап 3: базовый маркетплейс (каталог, потребности, предложения, сделки, мощности, документы, Capability Passport, уведомления, Playwright) — выполнено.

## Структура

```
apps/web/                    Next.js (App Router, TypeScript) — интерфейс
services/gateway-auth/       FastAPI — аккаунты, вход, компании, проверка
services/marketplace/        FastAPI — каталог/потребности/сделки (этап 3)
services/{agent-orchestrator,optimizer,llm-gateway,evidence-audit}/  (этап 4+)
packages/{contracts,ui}/     общие пакеты (pnpm workspace)
infra/                       docker-compose.yml, миграции, скрипты проверки
docs/                        mvp/, demo/, api/, architecture/
```

## Требования

- Docker Desktop / Docker Engine с Docker Compose;
- Node.js 20+ и pnpm;
- Python 3.12 (для локального запуска сервисов без Docker);
- Ollama с моделью `qwen3.5:9b` (нужна с этапа 4; для этапа 2 не обязательна).

## Быстрый старт

```bash
cp .env.example .env          # при необходимости задайте JWT_SECRET
docker compose -f infra/docker-compose.yml up --build
```

После запуска:

| Сервис | Адрес | Описание |
| --- | --- | --- |
| Web App | http://localhost:3000 | интерфейс покупателя/производителя/админа |
| Gateway Auth | http://localhost:8001 | аккаунты, вход, компании, проверка (OpenAPI: `/docs`) |
| Marketplace | http://localhost:8002 | каталог, потребности, предложения, сделки, уведомления (OpenAPI: `/docs`) |
| MinIO | http://localhost:9000 | объектное хранилище файлов (консоль: :9001) |
| PostgreSQL | localhost:5433 | БД (внутри Docker — хост `postgres:5432`) |

Миграции применяются и демо-аккаунты создаются автоматически при старте `gateway-auth`.

### Демо-аккаунты (синтетические)

| Роль | Email | Пароль |
| --- | --- | --- |
| Администратор | `admin@demo.ru` | `admin123` |
| Покупатель + продавец (проверенная компания) | `demo@demo.ru` | `demo123` |
| Производитель «СтаканОпт Демо» | `seller@demo.ru` | `seller123` |

## Локальный запуск сервисов без Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -r services/gateway-auth/requirements-dev.txt \
                        -r services/marketplace/requirements-dev.txt

# миграции (при запущенном PostgreSQL)
cd services/gateway-auth
DATABASE_URL=postgresql+asyncpg://sborka:sborka@localhost:5433/sborka ../../.venv/bin/alembic upgrade head
../../.venv/bin/python seed.py
DATABASE_URL=postgresql+asyncpg://sborka:sborka@localhost:5433/sborka ../../.venv/bin/uvicorn app.main:app --reload --port 8001
```

## Тесты

```bash
# создать тестовые БД один раз
docker compose -f infra/docker-compose.yml exec -T postgres psql -U sborka -d postgres -c "CREATE DATABASE sborka_test"
docker compose -f infra/docker-compose.yml exec -T postgres psql -U sborka -d postgres -c "CREATE DATABASE sborka_marketplace_test"

cd services/gateway-auth
TEST_DATABASE_URL=postgresql+asyncpg://sborka:sborka@localhost:5433/sborka_test ../../.venv/bin/pytest

cd ../marketplace
TEST_DATABASE_URL=postgresql+asyncpg://sborka:sborka@localhost:5433/sborka_marketplace_test ../../.venv/bin/pytest
```

### Playwright (E2E)

```bash
cd tests/e2e
pnpm install
pnpm install:browsers   # один раз — скачает Chromium
docker compose -f ../../infra/docker-compose.yml up --build   # поднимите стек
pnpm test
```

CI (`.github/workflows/ci.yml`) выполняет миграции и тесты бэкенда, а также type-check и сборку фронтенда.

## Проверка Ollama (Qwen3.5 9B)

```bash
python infra/verify_ollama.py
```

Результаты замера на основном компьютере — в `docs/architecture/ollama-benchmark.md`.

## Документация

Основной план — `plan_sborka_b2b.md`. Результаты этапа 1 — `docs/mvp/`, `docs/demo/`, `packages/test-fixtures/`. API-контракты — `docs/api/auth-api.md` (gateway-auth) и `docs/api/marketplace-api.md` (marketplace).

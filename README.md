# Сборка B2B

Прототип B2B-маркетплейса, создающего коалиции покупателей и производителей и моделирующего устойчивость сделки.

## Статус

- Этап 0: создание репозитория и фиксация архитектуры — выполнено.
- Этап 1: границы MVP, пользовательские сценарии и синтетические данные — выполнено.
- Этап 2: каркас и инфраструктура (монорепозиторий, Docker Compose, Web App, Gateway Auth, Marketplace, PostgreSQL, миграции, CI, проверка Ollama) — выполнено.
- Этап 3: базовый маркетплейс (каталог, потребности, предложения, сделки, мощности, документы, Capability Passport, уведомления, Playwright) — выполнено.
- Этап 4: локальная LLM, восстановление требований, доказательства и агенты — реализовано.
- Этап 5: коалиции покупателей, рыночные возможности и OR-Tools-оптимизатор — реализовано.
- Этап 6: горячий/тёплый/холодный резерв, N-1/N-2 и безопасное восстановление — реализовано.
- Этап 7: Human Approval Guard, проверяемый аудит, KPI, поддержка и проектные правовые материалы — реализовано.
- Этап 8: полировка, конкурсный прототип, офлайн-режим демо и материалы подачи — выполнено.
- Этап 9: персональный путь, сопровождение сделки, отзывы, индекс цен и база знаний — реализовано.

## Структура

```
apps/web/                    Next.js (App Router, TypeScript) — интерфейс
services/gateway-auth/       FastAPI — аккаунты, вход, компании, проверка
services/marketplace/        FastAPI — каталог/потребности/сделки
services/llm-gateway/        FastAPI — обработка материалов и агенты (этап 4)
services/optimizer/          FastAPI + OR-Tools — распределение объёма, коалиции и N-1/N-2
services/evidence-audit/     зарезервирован для следующих этапов
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

Для функций этапа 4 Ollama запускается на хосте отдельно:

```bash
ollama pull qwen3.5:9b
ollama serve
```

Базовый маркетплейс работает и без модели; в этом случае недоступен только
разбор новых материалов. Первая расшифровка аудио загружает локальную модель
Whisper `small` в Docker volume. DeepSeek необязателен и включается только через
`DEEPSEEK_API_KEY` в локальном `.env`; ключ нельзя добавлять в Git.
Для Docker адрес Ollama задаётся отдельно как
`OLLAMA_DOCKER_BASE_URL=http://host.docker.internal:11434`.

После запуска:

| Сервис | Адрес | Описание |
| --- | --- | --- |
| Web App | http://localhost:3000 | интерфейс покупателя/производителя/админа |
| Gateway Auth | http://localhost:8001 | аккаунты, вход, компании, проверка (OpenAPI: `/docs`) |
| Marketplace | http://localhost:8002 | каталог, потребности, предложения, сделки, уведомления (OpenAPI: `/docs`) |
| LLM Gateway | http://localhost:8003 | восстановление требований и агенты (OpenAPI: `/docs`) |
| Optimizer | http://localhost:8004 | детерминированные варианты, MOQ, скидки и коалиции (OpenAPI: `/docs`) |
| MinIO | http://localhost:9000 | объектное хранилище файлов (консоль: :9001) |
| PostgreSQL | http://localhost:5433 | БД (внутри Docker — хост `postgres:5432`) |
| pgAdmin | http://localhost:5050 | веб-интерфейс для просмотра локальной PostgreSQL |

В pgAdmin войдите с `PGADMIN_DEFAULT_EMAIL` и `PGADMIN_DEFAULT_PASSWORD` из
локального `.env`. При первом подключении зарегистрируйте сервер с параметрами:
хост `postgres`, порт `5432`, база и пользователь из `POSTGRES_DB` и
`POSTGRES_USER`, пароль из `POSTGRES_PASSWORD`. Данные pgAdmin сохраняются в
Docker volume `pgadmin_data` и не попадают в Git.

Миграции применяются и демо-аккаунты создаются автоматически при старте `gateway-auth`.

### Доступ с других устройств в локальной сети

Чтобы открыть сайт с телефона или другого устройства в той же сети, узнайте
адрес машины с запущенным Docker:

```bash
python scripts/print-access-url.py
# Сайт доступен с других устройств в той же сети: http://192.168.1.50:3000
```

CORS сервисов разрешает любые приватные локальные подсети (10.x, 172.16–31.x,
192.168.x), поэтому адрес работает при любой смене сети или IP без
перенастройки.

### Демо-аккаунты (синтетические)

| Роль | Email | Пароль |
| --- | --- | --- |
| Администратор | `admin@demo.ru` | `admin123` |
| Покупатель + продавец (проверенная компания) | `demo@demo.ru` | `demo123` |
| Производитель «СтаканОпт Демо» | `seller@demo.ru` | `seller123` |

После входа откройте «Создать потребность»: верхний блок принимает обычный
русский текст, фото, PDF и голос, показывает источники и противоречия, а затем
переносит только подтверждённые данные в карточку.

## Локальный запуск сервисов без Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -r services/gateway-auth/requirements-dev.txt \
                        -r services/marketplace/requirements-dev.txt \
                        -r services/llm-gateway/requirements-dev.txt \
                        -r services/optimizer/requirements-dev.txt

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

cd ../llm-gateway
TEST_DATABASE_URL=postgresql+asyncpg://sborka:sborka@localhost:5433/sborka_test ../../.venv/bin/pytest

cd ../optimizer
../../.venv/bin/pytest
```

Опциональный smoke-тест с реальной локальной Qwen (Ollama должна быть запущена):

```bash
cd services/llm-gateway
RUN_OLLAMA_SMOKE=1 OLLAMA_BASE_URL=http://localhost:11434 ../../.venv/bin/pytest -m ollama
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

Сравнение Qwen и необязательного DeepSeek на одинаковых синтетических задачах:

```bash
python infra/compare_llm_routes.py
```

Если IP сменится (переподключились к другой сети) — узнайте новый адрес одной командой на ноутбуке:

```bash
python scripts/print-access-url.py
```

И откройте новый http://<новый-IP>:3000. Ничего настраивать и пересобирать не нужно — CORS уже разрешает любые приватные подсети.

## Документация

Основной план — `plan_sborka_b2b.md`. Результаты этапа 1 — `docs/mvp/`, `docs/demo/`, `packages/test-fixtures/`. API-контракты — в `docs/api/`, архитектура устойчивости — `docs/architecture/stage-6-resilience.md`, контроль этапа 7 — `docs/architecture/stage-7-trust-control.md`, сопровождение сделки — `docs/architecture/stage9-experience.md`. Юридические файлы в `docs/legal/` являются проектными черновиками до проверки российским юристом.

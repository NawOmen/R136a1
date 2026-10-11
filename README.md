# Сборка B2B

Прототип B2B-маркетплейса, создающего коалиции покупателей и производителей и моделирующего устойчивость сделки.

## С чего продолжать

Единственный актуальный план — [NEXT_STEPS.md](NEXT_STEPS.md): подробные этапы 00–19, текущая база, оставшиеся функции, все категории, пять критериев конкурса и порядок подачи. Следующий исполнитель начинает с S00.01, затем предметных профилей S01; статусы/доказательства обновляет в этом же файле.

В коде есть основные пути покупателя и поставщика, агенты, коалиции, резерв, исполнение и аналитика; их наличие не означает завершения всех требований. На базе `a4ecbb3` стандартный Docker-стенд и 245 автоматических проверок прошли успешно. [Результаты, происхождение и ограничения](docs/reviews/verification-baseline.md). Оставшиеся задачи не помечаются выполненными по одному зелёному CI.

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
docs/                        demo/, api/, architecture/, contest/, research/
```

## Требования

- Docker Desktop / Docker Engine с Docker Compose;
- Node.js 20+ и pnpm;
- Python 3.12 (для локального запуска сервисов без Docker);
- Ollama с моделью `qwen3.5:9b` (нужна с этапа 4; для этапа 2 не обязательна).

## Быстрый старт

```bash
python3 scripts/init-local-env.py  # новый .env со случайными секретами, без перезаписи
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

MinIO собирается из исходников фиксированного коммита с проверкой SHA-256, поэтому первый запуск требует загрузки Go-модулей и занимает больше времени. Готовый образ MinIO из удалённого registry не требуется. Происхождение сборки и соответствующие исходники: [infra/minio/README.md](infra/minio/README.md).

Если стенд уже запускался раньше (на компьютере остался том PostgreSQL),
`init-local-env.py` предупредит об этом, а сервисы упадут с
`password authentication failed for user "sborka"`: PostgreSQL применяет
`POSTGRES_PASSWORD` только при первой инициализации тома, и смена `.env` пароль
роли не меняет. Перед запуском выполните один раз:

```bash
python3 scripts/sync-db-password.py   # выставит пароль роли из .env, данные сохранятся
```

Если данные не нужны, вместо этого удалите том (они будут потеряны):

```bash
docker compose --env-file .env -f infra/docker-compose.yml down
docker volume rm infra_postgres_data   # имя тома уточните: docker volume ls | grep postgres
```

Тот же шаг нужен после ротации `POSTGRES_PASSWORD` на существующем стенде;
подробности — в [docs/security/hardening.md](docs/security/hardening.md).

Для функций этапа 4 Ollama запускается на хосте отдельно:

```bash
ollama pull qwen3.5:9b
ollama serve
```

Базовый маркетплейс работает и без модели; в этом случае недоступен только
разбор новых материалов. Whisper `small` использует кеш в Docker volume.
Перед первым аудиозапросом подготовьте веса (скачиваются только веса модели,
пользовательские материалы не передаются):

```bash
docker compose -f infra/docker-compose.yml exec llm-gateway python -c 'from faster_whisper.utils import download_model; download_model("small")'
```

Обработчик аудио использует только этот локальный кеш; при отсутствии модели возвращает сообщение о временной недоступности. DeepSeek необязателен и включается только через
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

Миграции применяются при старте. Демо-аккаунты создаются только при явном
`ENABLE_DEMO_SEED=true`; пароли берутся из локального .env.
Для существующей базы обязательно выполнить [инструкцию смены секретов](docs/security/hardening.md).

### Доступ с других устройств в локальной сети

Базовый Compose доступен только на localhost. Для других устройств включите
[HTTPS-прокси и доверенный сертификат](docs/security/hardening.md).
Прямые API и служебные порты в сеть не публикуйте.

### Демо-аккаунты (синтетические)

| Роль | Email | Пароль |
| --- | --- | --- |
| Администратор | `admin@demo.ru` | `SEED_ADMIN_PASSWORD` из .env |
| Покупатель + продавец (проверенная компания) | `demo@demo.ru` | `SEED_DEMO_PASSWORD` из .env |
| Производитель «СтаканОпт Демо» | `seller@demo.ru` | `SEED_SELLER_PASSWORD` из .env |

После входа откройте «Создать потребность»: верхний блок принимает обычный
русский текст, фото, PDF и голос, показывает источники и противоречия, а затем
переносит только подтверждённые данные в карточку.

## Локальный запуск сервисов без Docker

Нужен Python 3.12, запущенные PostgreSQL и MinIO. Для нового стенда создайте
`.env` через `python3 scripts/init-local-env.py`; для существующего сначала выполните
[ротацию секретов](docs/security/hardening.md). Следующие команды выполняются
из корня проекта в bash/zsh. Загружайте только собственный доверенный `.env`:

```bash
set -a
. ./.env
set +a
export OPTIMIZER_URL=http://127.0.0.1:8004
export OLLAMA_BASE_URL=http://127.0.0.1:11434

# Каждому сервису — собственное окружение, как в Docker и CI.
for service_name in gateway-auth marketplace llm-gateway optimizer; do
  python3.12 -m venv "services/$service_name/.venv"
  "services/$service_name/.venv/bin/python" -m pip install "pytest>=8,<9" "pytest-asyncio>=0.26,<1" "httpx>=0.27,<1"
  "services/$service_name/.venv/bin/python" -m pip install --require-hashes -r "services/$service_name/requirements.lock"
  "services/$service_name/.venv/bin/python" -m pip check
done

# миграции (при запущенном PostgreSQL)
for service_name in gateway-auth marketplace llm-gateway; do
  (cd "services/$service_name" && .venv/bin/alembic upgrade head)
done

# Только для синтетического демо: явный флаг, пароли SEED_*_PASSWORD из .env.
export ENABLE_DEMO_SEED=true
if [ "$ENABLE_DEMO_SEED" = "true" ]; then
  (cd services/gateway-auth && .venv/bin/python seed.py)
  (cd services/marketplace && .venv/bin/python seed.py)
fi
export ENABLE_DEMO_SEED=false

# Запуск авторизации; для остальных сервисов — отдельные терминалы.
cd services/gateway-auth
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --no-proxy-headers --no-access-log
```

В каждом новом терминале сначала загрузите `.env` из корня теми же командами
`set -a; . ./.env; set +a` и экспортируйте указанные локальные URL.
Для marketplace, llm-gateway и optimizer перейдите в соответствующий каталог
`services/...` и выполните ту же команду uvicorn с портами 8002, 8003 и 8004.
Обязательны JWT_SECRET для авторизации/marketplace/LLM, OPTIMIZER_TOKEN для
marketplace/optimizer и MINIO_SECRET_KEY для marketplace. DATABASE_URL должен
содержать **текущий** пароль PostgreSQL. Флаг seed сам по себе не создаёт секреты.

## Тесты

После установки отдельных окружений и загрузки собственного `.env` из корня:

```bash
# Создать отдельную тестовую БД один раз (для PostgreSQL из Compose).
docker compose --env-file .env -f infra/docker-compose.yml exec -T postgres psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE sborka_test"
# Сохраняет подключение и пароль из DATABASE_URL, меняет только имя базы.
export TEST_DATABASE_URL="${DATABASE_URL%/*}/sborka_test"
for service_name in gateway-auth marketplace llm-gateway optimizer; do
  (cd "services/$service_name" && .venv/bin/python -m pytest -q)
done
```

Тесты очищают свои таблицы; TEST_DATABASE_URL должен указывать только на тестовую БД.
Для PostgreSQL без Docker создайте sborka_test через локальный psql.

Опциональный smoke-тест с реальной локальной Qwen (Ollama должна быть запущена):

```bash
cd services/llm-gateway
RUN_OLLAMA_SMOKE=1 OLLAMA_BASE_URL=http://localhost:11434 .venv/bin/python -m pytest -m ollama
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

Очередь работы и статусы — [NEXT_STEPS.md](NEXT_STEPS.md). Предметная спецификация — `plan_sborka_b2b.md`; сценарии и входные данные — `docs/demo/`, `packages/test-fixtures/`. API-контракты — в `docs/api/`, архитектура устойчивости — `docs/architecture/stage-6-resilience.md`, контроль этапа 7 — `docs/architecture/stage-7-trust-control.md`, сопровождение сделки — `docs/architecture/stage9-experience.md`. Юридические файлы в `docs/legal/` являются проектными черновиками до проверки российским юристом.

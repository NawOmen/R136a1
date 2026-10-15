# ПоРукам — B2B-маркетплейс

Российские покупатели и производители, каталог, потребности, КП, коалиции,
резерв, исполнение и аналитика. Расчёты выполняются кодом и OR-Tools;
локальная модель помогает обрабатывать материалы и готовить предложения.

**Запуск приложения — только через Docker.** Для размещения сайта на сервере
и подключения двух ноутбуков с моделями используйте
[DEPLOYMENT.md](DEPLOYMENT.md): RTX 5060 и MacBook, SSH-туннели, HTTPS,
ручное переключение, автоматическое резервирование и распределение запросов.

Актуальные задачи и доказательства готовности — [NEXT_STEPS.md](NEXT_STEPS.md).
Наличие функции и зелёный CI не подтверждают все условия эксплуатации.

## Требования

- Docker Engine с плагином Compose v2 на Linux либо Docker Desktop.
- Git и терминал bash/zsh; для Windows — WSL2.
- Для ИИ — Docker-узел Ollama по инструкции ниже или два ноутбука по
  [серверной инструкции](DEPLOYMENT.md).

Node.js, Python, PostgreSQL и зависимости приложения устанавливаются в образы.
Создавать окружения сервисов или запускать их отдельно на хосте не требуется.

## Docker-стенд на одном компьютере

Все команды — из корня репозитория. Для **нового** стенда создайте секреты:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace \
  python:3.12-slim python scripts/init-local-env.py
```

Скрипт не перезаписывает существующий `.env`. Контейнер подготовки не видит
список томов хоста: если PostgreSQL уже запускалась, сначала выполните
[порядок обновления и ротации](docs/security/hardening.md#существующая-база-и-ротация).
Не создавайте новые секреты вместо существующих без их согласованной смены.

Для Ollama подготовьте контейнер и модель:

```bash
docker run -d --name porukam-ollama --restart unless-stopped \
  -e OLLAMA_NO_CLOUD=1 \
  -p 127.0.0.1:11434:11434 -v porukam_ollama:/root/.ollama \
  ollama/ollama:latest
docker exec porukam-ollama ollama pull qwen3.5:9b
```

Это вариант на CPU. Для NVIDIA и настройки двух узлов см.
[DEPLOYMENT.md](DEPLOYMENT.md). Docker Desktop на macOS не предоставляет
Ollama GPU-ускорение Apple; измерения прежнего запуска на Mac нельзя переносить
на этот контейнер. Не запускайте второй контейнер, если имя/порт уже заняты:
проверьте `docker ps -a` и используйте существующий проверенный экземпляр.

В `.env` задайте:

```dotenv
OLLAMA_DOCKER_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
DEEPSEEK_API_KEY=
ENABLE_DEMO_SEED=false
```

Запустите сервисы:

```bash
docker compose --project-name infra --env-file .env -f infra/docker-compose.yml up -d --build
docker compose --project-name infra --env-file .env -f infra/docker-compose.yml ps
```

Миграции применяются entrypoint-контейнерами. Первый build MinIO собирает
фиксированный исходный код с проверкой SHA-256 и требует доступа к Go-модулям:
[происхождение сборки](infra/minio/README.md).

Для аудио один раз подготовьте кеш Whisper **в контейнере Gateway**:

```bash
docker compose --project-name infra --env-file .env -f infra/docker-compose.yml \
  exec llm-gateway python -c 'from faster_whisper.utils import download_model; download_model("small")'
```

Скачиваются веса, а не отправляются пользовательские материалы. Без кеша аудио
возвращает диагностируемую недоступность. Без доступной Ollama обязательное
извлечение новых материалов также не выполняется; ручные пути остаются доступны.

| Компонент | Доступ на компьютере Docker |
| --- | --- |
| Сайт | http://localhost:3000 |
| Auth / Marketplace / LLM Gateway | http://localhost:8001 / http://localhost:8002 / http://localhost:8003; OpenAPI `/docs` |
| PostgreSQL | TCP `127.0.0.1:5433`; внутри Compose — `postgres:5432` |
| MinIO / консоль | http://localhost:9000 / http://localhost:9001 |
| pgAdmin | http://localhost:5050 |
| Optimizer | Только внутри Compose: `http://optimizer:8004` |

Базовый Compose привязывает опубликованные порты к loopback. Со второго устройства
используйте HTTPS-прокси из [DEPLOYMENT.md](DEPLOYMENT.md), а не IP с портом 3000.
Для pgAdmin параметры подключения — `postgres:5432`, база/пользователь/пароль из
`.env`. Секреты, сертификаты и исходные клиентские файлы в Git не добавляются.

## Синтетическое наполнение

На пустой тестовой базе при необходимости задайте `ENABLE_DEMO_SEED=true`,
проверьте случайные `SEED_*_PASSWORD` в `.env` и выполните тот же `up -d --build`.
Auth создаёт аккаунты перед начальным наполнением Marketplace. После подготовки
верните флаг в `false` и повторите `up -d`. Для рабочего серверного развёртывания
seed оставляют выключенным. [Состав и правила повторного наполнения](docs/synthetic-assortment.md).

## Остановка и обновление

```bash
docker compose --project-name infra --env-file .env -f infra/docker-compose.yml logs --tail=100 llm-gateway
docker compose --project-name infra --env-file .env -f infra/docker-compose.yml stop
```

`stop` сохраняет контейнеры и тома; для продолжения выполните `up -d`.
Перед обновлением подготовьте резервную копию по
[операционному порядку](docs/operations/stage-15.md). Не используйте `down -v`
для обновления или смены пароля: это удаляет данные. Для HTTPS/модельного прокси
во всех командах сохраняйте набор Compose-файлов из серверной инструкции.

## Проверки

Проверки не требуют отдельного запуска приложения без Docker. CI выполняет
миграции, серверные тесты, клиентские проверки и сборку контейнера интерфейса.
Короткий серверный прогон можно выполнить Docker-runner'ом:

```bash
python3 scripts/test-backend.py --service marketplace -- -q tests/test_seed_catalog.py
```

Здесь Python 3 — только управляющая утилита на хосте; сервис, зависимости,
декодеры и временная PostgreSQL работают в изолированных Docker-контейнерах.
Runner не меняет рабочие тома и не использует секреты стенда. При первой сборке
нужна сеть. Полный набор запускается тем же runner'ом без `--service`.
Проверки живой модели и браузерная приёмка отделены от сборки; порядок серверной
проверки модели приведён в [DEPLOYMENT.md](DEPLOYMENT.md).

## Структура и документация

```text
apps/web/                  Next.js / React / TypeScript
services/gateway-auth/     аккаунты, компании и доступ
services/marketplace/      каталог, потребности, сделки и исполнение
services/llm-gateway/      извлечение материалов, агенты, OCR и Whisper
services/optimizer/        детерминированный расчёт / OR-Tools
infra/                    Compose, HTTPS-прокси, модели и сборка MinIO
```

- [Развёртывание: сервер и два ноутбука](DEPLOYMENT.md).
- [Оглавление документации](docs/README.md), [API](docs/api/marketplace-api.md),
  [безопасный запуск и ротация](docs/security/hardening.md).
- [Основная спецификация](plan_sborka_b2b.md) и [актуальная очередь](NEXT_STEPS.md).
- [Историческая проверенная база и её ограничения](docs/reviews/verification-baseline.md).

Данные наполнения синтетические. Юридические файлы в `docs/legal/` — проекты,
требующие утверждения и проверки применимости к реальному использованию.

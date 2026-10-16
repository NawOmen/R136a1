# Перечень лицензий сторонних компонентов

> Проектный документ для конкурсной подачи по п. 6.15 положения RLT.StartUp: гарантии использования сторонних компонентов на законном основании. Данные собраны из локальных метаданных установленных пакетов и не являются юридическим заключением; позиции с пометкой «требует проверки» подтверждаются вручную.

Версии в таблицах согласованы с объединённым обновлением Dependabot и lock-файлами
ветки Python 3.14. Исторические даты проверок ниже не являются новой юридической
проверкой всего набора; наличие версии в таблице не снимает отмеченные ограничения.

## 1. Прямые зависимости Node.js

| Пакет | Ограничение версии | Лицензия | Где объявлен |
|---|---|---|---|
| `next` | `^16.4.0` | MIT | `apps/web/package.json` (dependencies) |
| `react` | `^19.3.0` | MIT | `apps/web/package.json` (dependencies) |
| `react-dom` | `^19.3.0` | MIT | `apps/web/package.json` (dependencies) |
| `@types/node` | `^26.6.5` | MIT | `apps/web/package.json` (devDependencies) |
| `@types/react` | `^19.3.0` | MIT | `apps/web/package.json` (devDependencies) |
| `@types/react-dom` | `^19.3.0` | MIT | `apps/web/package.json` (devDependencies) |
| `typescript` | `^7.0.2` | Apache-2.0 | `apps/web/package.json` (devDependencies) |
| `@playwright/test` | `^1.64.0` | Apache-2.0 | `tests/e2e/package.json` (devDependencies) |

Транзитивные зависимости проверены 11.10.2026 командой `pnpm licenses list --prod`: набор лицензий — MIT, Apache-2.0, ISC, BSD-3-Clause, 0BSD, CC-BY-4.0 (данные `caniuse-lite`) и LGPL-3.0-or-later. Единственный copyleft-компонент — предсобранный платформенный пакет `@img/sharp-libvips-darwin-arm64 1.3.4` (зависимость `sharp`, используется Next.js для оптимизации изображений): немодифицированный бинарник, динамическая компоновка, в Docker-сборке подставляется linux-вариант. Совместимость LGPL при таком использовании подтверждает юрист; замена/исключение при необходимости оформляется отдельно.

## 2. Зависимости Python по сервисам

### gateway-auth

| Пакет | Версия | Лицензия |
|---|---|---|
| `alembic` | 1.20.0 | MIT |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `asyncpg` | 0.32.0 | Apache-2.0 |
| `bcrypt` | 4.3.0 | Apache-2.0 |
| `click` | 8.5.0 | BSD-3-Clause |
| `dnspython` | 2.8.0 | ISC |
| `email-validator` | 2.3.0 | Unlicense |
| `fastapi` | 0.143.0 | MIT |
| `opentelemetry-api` | 1.45.1 | Apache-2.0 |
| `greenlet` | 3.5.5 | MIT AND PSF-2.0 |
| `h11` | 0.16.0 | MIT |
| `httptools` | 0.8.0 | MIT |
| `idna` | 3.19 | BSD-3-Clause |
| `mako` | 1.4.1 | MIT |
| `markupsafe` | 3.0.3 | BSD-3-Clause |
| `pydantic` | 2.14.1 | MIT |
| `pydantic-core` | 2.50.1 | MIT |
| `pydantic-settings` | 2.15.0 | MIT |
| `pyjwt` | 2.15.1 | MIT |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |
| `pyyaml` | 6.0.3 | MIT |
| `sqlalchemy` | 2.1.4 | MIT |
| `starlette` | 1.6.0 | BSD-3-Clause |
| `typing-extensions` | 4.16.0 | PSF-2.0 |
| `typing-inspection` | 0.4.4 | MIT |
| `uvicorn` | 0.54.0 | BSD-3-Clause |
| `uvloop` | 0.22.1 | MIT License |
| `watchfiles` | 1.2.0 | MIT |
| `websockets` | 17.1 | BSD-3-Clause |

### llm-gateway

| Пакет | Версия | Лицензия |
|---|---|---|
| `alembic` | 1.20.0 | MIT |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `asyncpg` | 0.32.0 | Apache-2.0 |
| `av` | 18.1.0 | BSD-3-Clause |
| `certifi` | 2026.7.22 | MPL-2.0 |
| `click` | 8.5.0 | BSD-3-Clause |
| `ctranslate2` | 4.8.2 | MIT |
| `fastapi` | 0.143.0 | MIT |
| `opentelemetry-api` | 1.45.1 | Apache-2.0 |
| `faster-whisper` | 1.2.1 | MIT |
| `filelock` | 3.32.6 | MIT |
| `flatbuffers` | 25.12.19 | Apache 2.0 |
| `fsspec` | 2026.7.0 | BSD-3-Clause |
| `greenlet` | 3.5.5 | MIT AND PSF-2.0 |
| `h11` | 0.16.0 | MIT |
| `hf-xet` | 1.6.0 | Apache-2.0 |
| `httpcore` | 1.0.9 | BSD-3-Clause |
| `httptools` | 0.8.0 | MIT |
| `httpx` | 0.28.1 | BSD-3-Clause |
| `huggingface-hub` | 1.30.0 | Apache-2.0 |
| `idna` | 3.19 | BSD-3-Clause |
| `mako` | 1.4.1 | MIT |
| `markupsafe` | 3.0.3 | BSD-3-Clause |
| `numpy` | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `onnxruntime` | 1.29.0 | MIT License |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause |
| `protobuf` | 7.36.1 | 3-Clause BSD License |
| `pydantic` | 2.14.1 | MIT |
| `pydantic-core` | 2.50.1 | MIT |
| `pydantic-settings` | 2.15.0 | MIT |
| `pyjwt` | 2.15.1 | MIT |
| `pymupdf` | 1.28.2 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |
| `python-multipart` | 0.0.32 | Apache-2.0 |
| `pyyaml` | 6.0.3 | MIT |
| `sqlalchemy` | 2.1.4 | MIT |
| `starlette` | 1.6.0 | BSD-3-Clause |
| `tokenizers` | 0.23.2 | Apache Software License |
| `tqdm` | 4.70.0 | MPL-2.0 AND MIT |
| `typing-extensions` | 4.16.0 | PSF-2.0 |
| `typing-inspection` | 0.4.4 | MIT |
| `uvicorn` | 0.54.0 | BSD-3-Clause |
| `uvloop` | 0.22.1 | MIT License |
| `watchfiles` | 1.2.0 | MIT |
| `websockets` | 17.1 | BSD-3-Clause |
| `pillow` | 12.3.0 | MIT-CMU (Pillow и включённые компоненты: LICENSE дистрибутива) |

### marketplace

| Пакет | Версия | Лицензия |
|---|---|---|
| `alembic` | 1.20.0 | MIT |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `argon2-cffi` | 25.1.0 | MIT |
| `argon2-cffi-bindings` | 26.1.0 | MIT |
| `asyncpg` | 0.32.0 | Apache-2.0 |
| `certifi` | 2026.7.22 | MPL-2.0 |
| `cffi` | 2.1.1 | MIT-0 |
| `click` | 8.5.0 | BSD-3-Clause |
| `fastapi` | 0.143.0 | MIT |
| `opentelemetry-api` | 1.45.1 | Apache-2.0 |
| `greenlet` | 3.5.5 | MIT AND PSF-2.0 |
| `h11` | 0.16.0 | MIT |
| `httpcore` | 1.0.9 | BSD-3-Clause |
| `httptools` | 0.8.0 | MIT |
| `httpx` | 0.28.1 | BSD-3-Clause |
| `idna` | 3.19 | BSD-3-Clause |
| `mako` | 1.4.1 | MIT |
| `markupsafe` | 3.0.3 | BSD-3-Clause |
| `minio` | 7.2.20 | Apache-2.0 |
| `pycparser` | 3.0 | BSD-3-Clause |
| `pycryptodome` | 3.23.0 | BSD, Public Domain |
| `pydantic` | 2.14.1 | MIT |
| `pydantic-core` | 2.50.1 | MIT |
| `pydantic-settings` | 2.15.0 | MIT |
| `pyjwt` | 2.15.1 | MIT |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |
| `python-multipart` | 0.0.32 | Apache-2.0 |
| `pyyaml` | 6.0.3 | MIT |
| `sqlalchemy` | 2.1.4 | MIT |
| `starlette` | 1.6.0 | BSD-3-Clause |
| `typing-extensions` | 4.16.0 | PSF-2.0 |
| `typing-inspection` | 0.4.4 | MIT |
| `urllib3` | 2.8.0 | MIT |
| `uvicorn` | 0.54.0 | BSD-3-Clause |
| `uvloop` | 0.22.1 | MIT License |
| `watchfiles` | 1.2.0 | MIT |
| `websockets` | 17.1 | BSD-3-Clause |
| `pillow` | 12.3.0 | MIT-CMU (Pillow и включённые компоненты: LICENSE дистрибутива) |
| `pypdf` | 6.19.0 | BSD-3-Clause |
| `av` | 18.1.0 | BSD-3-Clause; предсобранные wheels включают FFmpeg (LGPL/GPL согласно LICENSE wheel) |

### optimizer

| Пакет | Версия | Лицензия |
|---|---|---|
| `absl-py` | 2.5.0 | Apache-2.0 |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `click` | 8.5.0 | BSD-3-Clause |
| `fastapi` | 0.143.0 | MIT |
| `opentelemetry-api` | 1.45.1 | Apache-2.0 |
| `h11` | 0.16.0 | MIT |
| `httptools` | 0.8.0 | MIT |
| `idna` | 3.19 | BSD-3-Clause |
| `immutabledict` | 4.3.1 | MIT |
| `numpy` | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `ortools` | 9.15.6755 | Apache 2.0 |
| `pandas` | 3.0.5 | BSD 3-Clause License |
| `protobuf` | 6.33.6 | 3-Clause BSD License |
| `pydantic` | 2.14.1 | MIT |
| `pydantic-core` | 2.50.1 | MIT |
| `pydantic-settings` | 2.15.0 | MIT |
| `python-dateutil` | 2.9.0.post0 | Dual License |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |
| `pyyaml` | 6.0.3 | MIT |
| `six` | 1.17.0 | MIT |
| `starlette` | 1.6.0 | BSD-3-Clause |
| `typing-extensions` | 4.16.0 | PSF-2.0 |
| `typing-inspection` | 0.4.4 | MIT |
| `uvicorn` | 0.54.0 | BSD-3-Clause |
| `uvloop` | 0.22.1 | MIT License |
| `watchfiles` | 1.2.0 | MIT |
| `websockets` | 17.1 | BSD-3-Clause |

## 3. Инфраструктура и внешние сервисы

| Компонент | Назначение | Лицензия или условия |
|---|---|---|
| PostgreSQL 16.4 (образ `postgres:16.4-alpine`) | база данных сервисов | PostgreSQL License (BSD-подобная) |
| MinIO (сборка `infra/minio/Dockerfile`, коммит `16f8cf1c52f0a77eeb8f7565aaf7f7df12454583`) | хранение документов и изображений | AGPL-3.0; LICENSE и соответствующие исходники включены в образ; см. `infra/minio/README.md` |
| nginx (`nginx:stable-alpine`) | HTTPS-прокси, единый origin | BSD-2-Clause |
| pgAdmin 4 | локальное администрирование базы, только для разработки | PostgreSQL License |
| Python 3.14 (образ `python:3.14-slim`) | среда выполнения сервисов | PSF License |
| Node.js 26 (образ `node:26-alpine`) | среда выполнения интерфейса | MIT |
| Ollama | локальный инференс агентов | код — MIT, [официальный LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE), проверен 11.10.2026; версия установленной среды должна фиксироваться оператором перед распространением |
| Qwen / Whisper | веса локальных моделей и STT | код `faster-whisper 1.2.1` — MIT, `ctranslate2 4.8.2` — MIT; лицензия конкретных весов (`qwen3.5:9b`, whisper `small`, см. `infra/models.lock.json`) не приложена — требуется проверка перед публикацией |
| OR-Tools | расчёты объединения спроса и устойчивости | Apache-2.0 |
| Playwright | браузерные и API-проверки | Apache-2.0 |

Внешние коннекторы и внешние модели в прототипе по умолчанию не используются. При подключении их условия проверяются отдельно, а клиентские файлы и персональные данные им не передаются.

## 4. Изображения, шрифты и иконки

Шрифты интерфейса системные; отдельных файлов шрифтов нет. Репозиторий содержит изображения:

| Ассет | Фактическое происхождение и назначение | Атрибуция / предел доказательства |
|---|---|---|
| `apps/web/app/icon.png` | Значок «ПоРукам», добавлен командой в коммите `acec45c` этапа 9 | Источник генерации и подтверждение авторства в метаданных файла не указаны; оператору нужно подтвердить права до внешнего распространения. Наличие в Git не доказывает авторство. |
| `packages/test-fixtures/buyer-evidence/photo/sample-cup.png` | Синтетический образец, созданный для проекта; описание в `photo-description.md` и `docs/demo/buyer-evidence-kit.md` | Нейтральный вымышленный логотип LOGO; не является фотографией реального производителя. |
| Пиктограммы групп ассортимента | Генерируются локальным кодом `group_pictogram` в `services/marketplace/seed_assortment.py` | Геометрические программные рисунки; внешний набор ассетов не используется. |

Для новых ассетов фиксируются источник, право использования и требуемая атрибуция. Утверждения о передаче всех прав на исходники либо лицензировании неизвестного ассета этим перечнем не делаются.

## 5. Что проверить вручную до подачи

1. Лицензии внешних сервисов из раздела 3: MinIO (AGPL-3.0), выбранная локальная модель, базовые образы Python и Node — подтвердить по документации этих проектов.
2. Условия использования выбранной локальной модели: разные модели выходят под разными лицензиями; лицензия весов в репозитории не зафиксирована.
3. Условия AGPL у MinIO и PyMuPDF/MuPDF для фактической архитектуры и способа использования, включая сетевое предоставление и распространение. PyMuPDF уже указан в таблице как dual-licensed; наличие метаданных не закрывает проверку условий. [Официальное описание лицензирования](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright). Фактический способ использования на 11.10.2026: MinIO — отдельный немодифицированный контейнер, доступ только по S3 API из сервисов, LICENSE и соответствующие исходники включены в образ (`infra/minio/Dockerfile`, `infra/minio/README.md`); PyMuPDF 1.28.2 — немодифицированная библиотека серверного парсинга PDF в `llm-gateway` (изолированный `file_worker.py`, вызываемый `extractors.py`); граница процесса не трактуется как освобождение от лицензии; sharp/libvips — немодифицированные предсобранные бинарники через пакетный менеджер. Вывод о достаточности этих мер делает юрист.
4. Отсутствие в демонстрационных материалах чужих брендов, логотипов, фотографий и текстов.
5. Сохранность файлов LICENSE установленных дистрибутивов и упоминание библиотек в приложении к презентации.

## 6. Ограничения документа

- Прямых Node-зависимостей: 8; Python-пакетов по четырём сервисам: 150 записей (31 + 42 + 48 + 29) (пакеты повторяются между сервисами).
- Все прямые зависимости Node и Python-пакеты из lock-файлов имеют указанную лицензию в метаданных; метаданные не подтверждают исполнение лицензионных обязанностей. Ручная сверка нужна также для выбранных библиотек, в частности PyMuPDF/MuPDF, моделей и ассетов, с учётом способа использования.
- Перечень собран из локальных метаданных на дату составления и обновляется после изменения зависимостей.
- Документ не заменяет юридическую проверку лицензий.

Обновление PR #124: версии FastAPI 0.143.0, SQLAlchemy 2.1.4, Uvicorn 0.54.0 и PyJWT 2.15.1 сверены с установленными метаданными четырёх изолированных сервисов. `opentelemetry-api` — обязательная транзитивная зависимость нового FastAPI, а не отдельная интеграция отправки телеметрии. Lock-файлы сохраняют хеши; установка проверена с `--require-hashes` и `pip check`.

Обновление по ревью PR #125: Pillow, pypdf и PyAV используются для настоящей проверки формата, страниц/пикселей/аудиокадров в ограниченном процессе. Это необходимые production-зависимости, а не декоративные библиотеки. Версии закреплены опубликованными SHA-256 хешами; PyMuPDF не добавлялся в marketplace. Предсобранные wheels PyAV требуют сверки состава FFmpeg и включённых лицензий при распространении, независимо от BSD-лицензии Python-обёртки.

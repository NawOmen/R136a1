# Docker: сайт на сервере, модели на двух ноутбуках

Инструкция описывает размещение на Linux-сервере с обычным rootful Docker Engine
и Compose v2. На ноутбуках — Docker Desktop либо Docker Engine; команды выполняются
в bash/zsh, на Windows — в WSL2. Docker rootless, Kubernetes и несколько серверов
требуют отдельной сетевой настройки. Ниже нет запуска сервисов приложения на хосте.
SSH, настройка ОС, домена и сертификата — инфраструктура соединения.

Это порядок развёртывания, а не отчёт о выполненном доступе к вашему серверу.
Замените `market.example.ru`, `SERVER_HOST` и адрес Docker-моста своими значениями.
Все команды серверных разделов выполняйте из корня checkout на сервере.

## 1. Где работает каждый компонент

| Место | Компоненты |
| --- | --- |
| Linux-сервер | Docker Compose: сайт, Auth, Marketplace, LLM Gateway, Optimizer, PostgreSQL, MinIO, pgAdmin; nginx HTTPS |
| Основной ноутбук | Intel Core Ultra 7 255H, RTX 5060 8 ГБ VRAM, 32 ГБ RAM; Docker Ollama с Qwen3.5 9B, основной узел |
| Резервный ноутбук | MacBook Pro 16, M1 Pro, 16 ГБ unified memory; второй Docker Ollama с той же моделью |
| Сервер, при автоматическом режиме | Внутренний Docker nginx `llm-router`, обращающийся к двум SSH-туннелям |

Это выбранная конфигурация стенда. Фактическая проверка RTX-ноутбука
описана в [комментарии PR #132](https://github.com/NawOmen/R136a1/pull/132#issuecomment-6211060164);
она относится к прежнему коммиту и хостовой Ollama, а не к GPU-контейнеру.
Whisper/OCR остаются внутри серверного LLM Gateway; Qwen выполняется на ноутбуках.
Файлы и состояние процесса хранятся на сервере. Gateway отправляет нужные для
локального инференса данные выбранному ноутбуку по шифрованному соединению.
Расчёты денег, объёма и N-1/N-2 выполняет серверный код, не ноутбучная LLM.

Предусмотрены три режима:

1. **Ручной:** один адрес Ollama в `.env`, переключение на другой ноутбук оператором.
2. **Основной/резерв:** nginx сначала использует RTX, при доступной резервной модели — MacBook.
3. **Распределение:** оба узла получают запросы через nginx.

Gateway сам не имеет пула узлов: автоматические режимы обеспечивает отдельный
Docker-прокси из раздела 7. Один запрос выполняется одной моделью; память двух
компьютеров не объединяется. Пробуйте режимы на синтетических материалах и измеряйте
задержки до использования с рабочими процессами.

### Что требуется от каждого ноутбука для связи с сервером

| Требование | Что подготовить / как проверить |
| --- | --- |
| ОС и Docker | На RTX — Linux либо Windows с WSL2 и доступом NVIDIA из Docker; на Mac — Docker Desktop. `docker info` должен выполняться без ошибки. |
| SSH-клиент | Команда `ssh -V`; SSH-сервер на ноутбуке не нужен. Ноутбук выступает клиентом и сам открывает туннель. |
| Доступ к серверу | Домен/IP сервера и его SSH-порт (по умолчанию TCP 22). Сеть ноутбука должна разрешать **исходящее** соединение к нему; при другом порте добавьте `-p НОМЕР` в команды SSH. |
| Доверие и ключ | Отдельный приватный ключ на каждом ноутбуке, соответствующий `.pub` на сервере, проверенный fingerprint сервера. Ключ должен быть доступен SSH при установке/восстановлении туннеля. |
| Модель | Работающий `porukam-ollama`, скачанная `qwen3.5:9b`, одинаковые проверенные digest модели на двух узлах. Локальный `/api/chat` должен возвращать результат, не только `/api/tags`. |
| Ресурсы | RAM/VRAM для модели и контекста 8192; место под образ и веса (в ТЗ веса около 6,6 ГБ), дополнительно под Docker/кеш. На Mac учитывайте выделенную Docker память, а не только 16 ГБ всей машины. Проверяйте OOM/swap и задержку; характеристики не заменяют измерение. |
| Непрерывная работа | Питание, охлаждение, запущенный Docker, запрет автоматического сна/отключения сети на время работы. Закрытая крышка не должна усыплять узел. |
| Сеть | Стабильная передача текста/изображений и ответа в пределах тайм-аутов. Измерьте реальную загрузку/генерацию, особенно через мобильную сеть; фиксированная пропускная способность без замеров не обещается. |
| Сеанс туннеля | Открытый SSH-сеанс из раздела 4 либо отдельно настроенный автозапуск/переподключение. `--restart unless-stopped` относится к Ollama, а не к SSH. |

Ноутбуки могут находиться в разных сетях за NAT, с динамическими IP. Им не нужны
публичный IP, общий Wi-Fi с сервером или проброс входящих портов домашнего роутера.
Ollama на ноутбуке слушает опубликованный Docker-порт только на loopback. Входящий
SSH и ограниченные reverse-forward разрешает **сервер**; если корпоративная сеть
блокирует исходящий SSH, сначала согласуйте доступ с её администратором.
Для скачивания образов/весов нужна сеть; после подготовки сам инференс выполняется
на ноутбуке. Для удалённого сайта связь ноутбука с сервером всё равно нужна.

## 2. Подготовка сервера и HTTPS

Нужны Git, Docker Engine с Compose v2, OpenSSH server, домен с DNS на сервер,
вход по SSH и доверенный TLS-сертификат. Docker ставьте по
[официальной инструкции для Linux](https://docs.docker.com/engine/install/).
Доступ к Docker даёт права управления сервером; предоставляйте его оператору.

```bash
git clone https://github.com/NawOmen/R136a1.git
cd R136a1
git switch main
git pull --ff-only

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace \
  python:3.14-slim python scripts/init-local-env.py
```

Инициализация предназначена для нового стенда. При переносе существующего сначала
сохраните `.env`, файлы, тома и резервную копию; используйте
[проверенный порядок восстановления](README.md#operations).
Скрипт внутри контейнера не проверяет старые Docker volumes хоста.

Сертификат с SAN вашего домена и цепочкой доверия положите **вне Git**, например:

```text
/srv/porukam-tls/fullchain.pem
/srv/porukam-tls/privkey.pem
```

Получение/продление сертификата выполняйте через вашего CA. Если используете
Certbot HTTP-01, во время проверки ему нужен порт 80; встроенный nginx не обслуживает
ACME challenge автоматически. DNS-01 не требует остановки edge. После продления
обновляйте эти файлы и перезагружайте nginx; истечение сертификата не исправляется
пересборкой приложения.

Сохраните в серверном `.env` дополнительно к сгенерированным секретам:

```dotenv
CORS_ORIGINS=https://market.example.ru
TLS_CERT_DIR=/srv/porukam-tls
OLLAMA_DOCKER_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3.5:9b
LLM_CONTEXT_TOKENS=8192
DEEPSEEK_API_KEY=
ENABLE_DEMO_SEED=false
```

Для этой схемы DeepSeek выключен. Файл `.env` не публикуйте и не выводите полным
`docker compose config` в общие журналы: подстановка содержит секреты.
Синтетические аккаунты включайте только отдельным явным решением.

Определите серверную команду Compose; далее `dc` используется только на сервере:

```bash
dc() {
  docker compose --project-name infra --env-file .env \
    -f infra/docker-compose.yml -f infra/docker-compose.https.yml "$@"
}
dc config --quiet
```

Проект `infra` сохранён для совместимости с существующими операционными скриптами
и именами томов. Для другого имени согласованно меняйте все команды и параметры
backup/restore; иначе можно получить новую пустую БД вместо старой.

Разрешите входящий HTTPS 443 и административный SSH; порт 80 нужен только при
выбранной схеме TLS/его проверке. Служебные порты 3000, 5050, 5433, 8001–8004,
9000/9001 и 11434/11435 не открывайте в публичной сети. В Compose внутренние
API и хранилища уже привязаны к loopback, Optimizer не публикуется.
Не заменяйте их привязки на `0.0.0.0`. Firewall проверяйте и с внешнего устройства.

Браузер открывает `https://market.example.ru` и обращается к `/gateway/`,
`/marketplace/`, `/llm/` на том же origin. Текущий клиент переводит встроенные
loopback API URL в эти HTTPS-пути; IP ноутбуков не задаётся в браузере.
HTTP на порту 80 возвращает отказ с указанием использовать HTTPS, не редирект.

## 3. Docker Ollama на обоих ноутбуках

Перед созданием контейнера на каждом ноутбуке проверьте `docker ps -a` и порт
11434. Если он занят прежним экземпляром Ollama, остановите тот экземпляр
средствами его управления; не запускайте две копии на одном порту. Существующий
Docker-контейнер можно продолжить через `docker start porukam-ollama` после
проверки его параметров. Старые веса не удаляйте ради освобождения порта.

### Ноутбук RTX 5060

В Linux подготовьте актуальный драйвер NVIDIA и
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
В Windows используйте WSL2 и поддерживаемый Docker GPU-путь. Сначала проверьте
`nvidia-smi` на ноутбуке; наличие видеокарты в ТЗ не подтверждает доступ из контейнера.

```bash
docker pull ollama/ollama:latest
docker run -d --name porukam-ollama --restart unless-stopped \
  --gpus all -e OLLAMA_NO_CLOUD=1 -e OLLAMA_NUM_PARALLEL=1 \
  -e OLLAMA_KEEP_ALIVE=30m \
  -p 127.0.0.1:11434:11434 -v porukam_ollama:/root/.ollama \
  ollama/ollama:latest
docker exec porukam-ollama ollama pull qwen3.5:9b
```

### MacBook M1 Pro

```bash
docker pull ollama/ollama:latest
docker run -d --name porukam-ollama --restart unless-stopped \
  -e OLLAMA_NO_CLOUD=1 -e OLLAMA_NUM_PARALLEL=1 \
  -e OLLAMA_KEEP_ALIVE=30m \
  -p 127.0.0.1:11434:11434 -v porukam_ollama:/root/.ollama \
  ollama/ollama:latest
docker exec porukam-ollama ollama pull qwen3.5:9b
```

**На Mac это CPU-инференс.** Docker Desktop на macOS не предоставляет GPU passthrough
для Ollama. Время прежнего нативного измерения Apple Silicon не является оценкой
Docker-режима; 9B может оказаться слишком медленной для текущих тайм-аутов.
Это нужно измерить до включения Mac в распределение. На RTX 8 ГБ также проверяйте
фактическое размещение, RAM/VRAM и задержку при контексте 8192, не обещая полного
помещения модели в VRAM. [Ограничение Ollama](https://docs.ollama.com/faq#how-do-i-use-ollama-with-gpu-acceleration-in-docker).

На **каждом** ноутбуке:

```bash
curl --fail --max-time 10 http://127.0.0.1:11434/api/tags
docker image inspect ollama/ollama:latest --format '{{json .RepoDigests}}'
docker exec porukam-ollama ollama list
```

Первичная загрузка требует интернета и места для образа/весов. Сохраните digest
образа и модели; `latest` — только начальная загрузка, не неизменяемая версия.
Для повторного развёртывания используйте проверенный `ollama/ollama@sha256:...`
вместо тега и одинаковый digest `qwen3.5:9b` на обоих узлах. Один тег не доказывает
одинаковые веса. Существующие нативные веса не становятся Docker-volume автоматически.
Не удаляйте старые веса до отдельной проверки новой схемы.

## 4. Два закрытых SSH-туннеля

Ноутбук сам соединяется с сервером, поэтому входящий порт на домашнем роутере не
нужен. На ноутбуке Ollama опубликована только на `127.0.0.1:11434`.
На сервере туннели слушают **адрес Docker-моста**, а не внешний интерфейс:

| Узел | Адрес на сервере | Назначение на соответствующем ноутбуке |
| --- | --- | --- |
| RTX | `DOCKER_GATEWAY:11434` | `127.0.0.1:11434` |
| Mac | `DOCKER_GATEWAY:11435` | `127.0.0.1:11434` |

Два одинаковых локальных порта не конфликтуют: это разные ноутбуки.
Простой `ssh -R 11434:...` с loopback-слушателем на сервере здесь не подходит:
серверный контейнер обращается к host-gateway, а не к loopback хоста.

На **сервере** узнайте фактическое значение, которое увидят контейнеры:

```bash
docker run --rm --add-host host.docker.internal:host-gateway \
  python:3.14-slim python -c 'import socket; print(socket.gethostbyname("host.docker.internal"))'
```

Далее пример использует `172.17.0.1`. Если вывод другой, замените адрес во всех
`PermitListen`, `-R` и проверках. Убедитесь, что он принадлежит внутреннему
Docker-мосту сервера, не публичному интерфейсу. Если daemon переопределяет
host-gateway или используется rootless Docker, сначала настройте этот путь.
Не исправляйте недоступность прослушиванием `0.0.0.0:11434`.

На ноутбуках создайте **разные** ключи (GPU/Mac соответственно):

```bash
# На RTX-ноутбуке:
ssh-keygen -t ed25519 -f ~/.ssh/porukam-ollama-gpu
# На MacBook:
ssh-keygen -t ed25519 -f ~/.ssh/porukam-ollama-mac
```

На **сервере** администратор создаёт двух пользователей для туннелей:

```bash
for tunnel_user in ollama-gpu ollama-mac; do
  sudo useradd --create-home --shell /bin/sh "$tunnel_user"
  sudo install -d -m 700 -o "$tunnel_user" -g "$tunnel_user" "/home/$tunnel_user/.ssh"
  sudo install -m 600 -o "$tunnel_user" -g "$tunnel_user" /dev/null "/home/$tunnel_user/.ssh/authorized_keys"
done
```

Это первичная настройка, не команда перезаписи существующих пользователей/ключей.
Через действующий административный SSH-доступ внесите содержимое GPU `.pub` в
`/home/ollama-gpu/.ssh/authorized_keys`, Mac `.pub` — в соответствующий файл
`ollama-mac`. Приватные ключи остаются на ноутбуках. Учётные записи должны допускать
аутентификацию ключом согласно политике вашего sshd/PAM.

Добавьте в серверный `/etc/ssh/sshd_config.d/porukam-models.conf`
(проверьте, что основной конфиг подключает этот каталог):

```text
Match User ollama-gpu,ollama-mac
    AuthenticationMethods publickey
    PasswordAuthentication no
    AllowTcpForwarding remote
    GatewayPorts clientspecified
    AllowAgentForwarding no
    AllowStreamLocalForwarding no
    X11Forwarding no
    PermitTTY no
    MaxSessions 0
Match User ollama-gpu
    PermitListen 172.17.0.1:11434
Match User ollama-mac
    PermitListen 172.17.0.1:11435
Match All
```

Оставьте текущий административный сеанс открытым. Проверьте конфиг и примените
его; на Ubuntu/Debian служба обычно называется `ssh`:

```bash
sudo /usr/sbin/sshd -t
sudo systemctl reload ssh
```

Не заменяйте `clientspecified` на `yes`: это меняет политику адреса прослушивания.
Проверьте применённые ограничения для обоих пользователей (`sshd -T -C ...`),
особенно если на сервере уже есть другие Match-правила. Существующий firewall
должен разрешать обращение контейнеров к этому внутреннему адресу/двум портам,
не разрешая их через публичный интерфейс.

На **RTX-ноутбуке** запустите:

```bash
SERVER_DOCKER_GATEWAY=172.17.0.1
ssh -NT -i ~/.ssh/porukam-ollama-gpu -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -R "$SERVER_DOCKER_GATEWAY:11434:127.0.0.1:11434" ollama-gpu@SERVER_HOST
```

На **MacBook** в своём терминале:

```bash
SERVER_DOCKER_GATEWAY=172.17.0.1
ssh -NT -i ~/.ssh/porukam-ollama-mac -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -R "$SERVER_DOCKER_GATEWAY:11435:127.0.0.1:11434" ollama-mac@SERVER_HOST
```

Подтвердите fingerprint сервера через доверенный административный канал.
Терминалы держат соединение; keepalive обнаруживает разрыв, но не переподключает
его. После смены сети/сна запустите ту же команду снова. Постоянную службу/автозапуск
настраивайте отдельно средствами ОС с теми же ограничениями ключа и адреса.

На **сервере** проверьте оба туннеля и привязки:

```bash
ss -ltn | grep -E '11434|11435'
curl --fail --max-time 10 http://172.17.0.1:11434/api/tags
curl --fail --max-time 10 http://172.17.0.1:11435/api/tags
```

В `ss` ожидается только внутренний адрес Docker-моста, без `0.0.0.0`/`[::]`/публичного IP.
Если второго ноутбука пока нет, его проверка ожидаемо не проходит; не считайте узел готовым.

## 5. Запуск сайта и ручное переключение

На сервере, после `.env`, TLS и нужного туннеля:

```bash
dc up -d --build
dc ps
dc exec llm-gateway python -c 'from faster_whisper.utils import download_model; download_model("small")'
```

Проверка из **самого Gateway-контейнера**, а не только с хоста:

```bash
dc exec -T llm-gateway python - <<'PY'
import json, os, urllib.request
base = os.environ['OLLAMA_BASE_URL'].rstrip('/')
with urllib.request.urlopen(base + '/api/tags', timeout=10) as response:
    print(json.load(response))
PY
```

Для RTX в `.env` — `OLLAMA_DOCKER_BASE_URL=http://host.docker.internal:11434`.
Для Mac — `OLLAMA_DOCKER_BASE_URL=http://host.docker.internal:11435`.
После изменения пересоздайте Gateway (обычный `restart` не читает новый `.env`):

```bash
dc up -d --no-deps --force-recreate llm-gateway
```

Открывайте `https://market.example.ru`. Проверьте вход, каталог, загрузку
синтетического документа, разбор и подтверждение требований. `/health` Gateway
проверяет процесс, а не успешный инференс Qwen. Сон/выключение выбранного ноутбука
или разрыв туннеля делает LLM-функции недоступными; автоматического перехода на другой
порт в ручном режиме нет. Подготовленные данные и ручные сценарии остаются на сервере.

## 6. Проверка настоящего инференса каждого узла

Проверяйте по одному ноутбуку до балансировки. На сервере:

```bash
curl --fail --max-time 180 http://172.17.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:9b","stream":false,"think":false,"messages":[{"role":"user","content":"Ответь одним словом: работает"}],"options":{"num_ctx":8192}}'
```

Повторите с `11435` для Mac. Убедитесь, что API вернул ответ, а не только список
моделей. На соответствующем ноутбуке `docker exec porukam-ollama ollama ps`
покажет размещение модели; `docker stats --no-stream porukam-ollama` — наблюдаемую
память контейнера. Сохраните задержку и результат без исходных клиентских материалов.
Не отправляйте параллельно много задач: у каждого Ollama задан один поток генерации.

## 7. Автоматические режимы через Docker nginx

Прямой endpoint Gateway заменяется на внутренний `http://llm-router:11434`.
На сервере создайте внешний каталог `/srv/porukam-ops` для двух файлов ниже.
Прокси не публикует порт на хосте и не доступен браузеру напрямую.

Файл `/srv/porukam-ops/llm-router.conf`, режим **основной/резерв**:

```nginx
upstream porukam_models {
    zone porukam_models 64k;
    server host.docker.internal:11434 max_fails=1 fail_timeout=30s;
    server host.docker.internal:11435 backup max_fails=1 fail_timeout=30s;
}
server {
    listen 11434;
    client_max_body_size 105m;
    access_log off;
    proxy_connect_timeout 3s;
    proxy_read_timeout 75s;
    proxy_send_timeout 75s;
    proxy_set_header Host localhost:11434;
    proxy_request_buffering on;
    proxy_buffering off;
    proxy_next_upstream error timeout http_500 http_502 http_503 http_504 non_idempotent;
    proxy_next_upstream_tries 2;
    proxy_next_upstream_timeout 160s;
    add_header X-Porukam-LLM-Attempts $upstream_addr always;
    location = /api/chat { proxy_pass http://porukam_models; }
    location = /api/tags { proxy_pass http://porukam_models; }
    location = /api/version { proxy_pass http://porukam_models; }
    location / { return 404; }
}
```

`host.docker.internal` в контейнере указывает на серверный Docker-мост с SSH-туннелями.
Это не адрес Docker Desktop ноутбука. Повтор POST разрешён **только для инференса**
`/api/chat`; здесь не проксируются действия Marketplace, цены, резервы или согласия.
Один LLM-запрос при сбое может быть вычислен повторно на втором узле; повтор запроса
не является повторным подтверждением бизнес-действия. Изменение модели/контекста
самим роутером не производится.

Для **распределения между обоими узлами** замените только upstream на:

```nginx
upstream porukam_models {
    zone porukam_models 64k;
    least_conn;
    server host.docker.internal:11434 weight=4 max_fails=1 fail_timeout=30s;
    server host.docker.internal:11435 weight=1 max_fails=1 fail_timeout=30s;
}
```

Веса 4:1 — начальный пример настройки, не измеренное соотношение скорости.
Повтор на другом узле разрешён при ошибке соединения, тайм-ауте или HTTP
500/502/503/504. Ответ HTTP 200 с неверным JSON или неподходящим содержимым
nginx не проверяет; содержимое проверяет Gateway. Пассивная проверка исключает
узел после учитываемой ошибки; активного фонового мониторинга
моделей в этой конфигурации нет. После 30 секунд возможна новая попытка к узлу.
Доступность `/api/tags` не означает, что модель укладывается в тайм-аут генерации.

Файл `/srv/porukam-ops/compose.llm-router.yml`:

```yaml
services:
  llm-router:
    image: nginx:stable-alpine
    restart: unless-stopped
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - /srv/porukam-ops/llm-router.conf:/etc/nginx/conf.d/default.conf:ro
    logging:
      driver: local
      options:
        max-size: "10m"
        max-file: "3"
  llm-gateway:
    environment:
      OLLAMA_BASE_URL: http://llm-router:11434
    depends_on:
      llm-router:
        condition: service_started
```

Остальные зависимости Gateway сохраняются при объединении Compose-файлов.
Файл и модельный прокси включаются **во все** команды этого режима:

```bash
dc_models() {
  docker compose --project-name infra --env-file .env \
    -f infra/docker-compose.yml -f infra/docker-compose.https.yml \
    -f /srv/porukam-ops/compose.llm-router.yml "$@"
}
dc_models config --quiet
dc_models up -d --build
dc_models exec llm-router nginx -t
```

Для смены upstream отредактируйте файл и выполните:

```bash
dc_models exec llm-router nginx -t
dc_models exec llm-router nginx -s reload
```

В режиме с overlay именно `OLLAMA_BASE_URL` из overlay имеет приоритет над
`OLLAMA_DOCKER_BASE_URL` из `.env`. Для возврата к ручному режиму выполните
`dc up -d --no-deps --force-recreate llm-gateway`, затем `dc_models stop llm-router`.
Не останавливайте прокси до переключения Gateway обратно на туннель.

При этих настройках у каждой попытки — read timeout 75 с, у маршрута — окно
повтора 160 с; это рассчитано на текущий тайм-аут Gateway 180 с и edge 240 с.
Тайм-аут nginx измеряет промежутки чтения, а не строгий общий deadline.
Если Mac/холодный старт не укладывается, не считайте резерв готовым: сначала
измерьте нагрузку и согласованно настройте Gateway, оба nginx и клиентский путь.
Смена только одного тайм-аута не продлевает остальные.

Проверка автоматического режима:

1. Убедитесь, что оба прямых порта проходят раздел 6 и имеют одинаковую модель.
2. Повторите проверку из Gateway (раздел 5): endpoint должен быть `llm-router`.
3. Сделайте синтетический `/api/chat` через router из контейнера: заголовок
   `X-Porukam-LLM-Attempts` показывает адреса попыток; приложения не обещают сохранять
   этот заголовок в своей истории.
4. В основном/резервном режиме остановите только GPU-туннель и повторите запрос:
   после сбоя основного ожидается обращение к Mac, если он отвечает вовремя.
5. В распределении проверьте несколько одновременных синтетических запросов и
   оба ноутбука через `ollama ps`. Последовательные короткие запросы не доказывают
   распределение при `least_conn`.
6. При отключении обоих узлов запрос должен завершиться диагностируемой ошибкой,
   не создавать заявку/согласие и не переключаться на внешнюю LLM. Для закрытого
   режима `DEEPSEEK_API_KEY` остаётся пустым.

## 8. Сопровождение и восстановление

- Ноутбуки должны быть включены, подключены к питанию и доступны по сети.
  Автоперезапуск Docker-контейнера не восстанавливает SSH после сна ноутбука.
- Compose приложения пока не задаёт всем сервисам restart policy. После перезагрузки
  сервера оператор повторяет `dc up -d` или `dc_models up -d`; для автоматического
  старта настройте инфраструктурную службу с теми же файлами и рабочим каталогом.
- До обновления сохраните checkout/commit, `.env`, TLS/туннельную конфигурацию,
  дамп PostgreSQL и файлы MinIO. Выполните [backup/restore](README.md#operations)
  с тем же Compose-проектом. Модельные volumes отдельно находятся на ноутбуках.
- Обновляйте через `git pull --ff-only` и выбранный `up -d --build` после проверки CI.
  Миграции применяются контейнерами; откат образа сам по себе не откатывает БД.
- Для ротации PostgreSQL используйте [порядок смены секретов](README.md#secure-deployment).
  Новый `POSTGRES_PASSWORD` не меняет пароль существующего тома автоматически.
- Продление TLS: после обновления файлов — `dc exec edge nginx -t`, затем
  `dc exec edge nginx -s reload` (либо те же команды через `dc_models`).
- Для диагностики — `dc ps`, `dc logs --tail=100 llm-gateway`, логи контейнера Ollama
  на выбранном ноутбуке. Перед передачей журналов удаляйте секреты и клиентские данные.
- Это небольшое развёртывание, не обещание высокой доступности: оба ноутбука могут
  потерять одну сеть/питание. Автобалансировка не заменяет резервную копию сервера.

## Источники и границы проверки

- [Ollama Docker](https://docs.ollama.com/docker),
  [GPU в Docker Desktop macOS](https://docs.ollama.com/faq#how-do-i-use-ollama-with-gpu-acceleration-in-docker).
- [Docker host-gateway](https://docs.docker.com/reference/cli/dockerd/#configure-host-gateway-ip).
- [OpenSSH GatewayPorts / PermitListen / MaxSessions](https://man.openbsd.org/sshd_config).
- [nginx upstream / backup / least_conn](https://nginx.org/en/docs/http/ngx_http_upstream_module.html),
  [повтор запроса и тайм-ауты](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_next_upstream).

Примеры сопоставлены с текущим Compose. Два настоящих ноутбука, ваш домен,
сертификат, серверный firewall и задержки инференса требуют проверки оператором;
документационная проверка не выдаётся за фактическое развёртывание.

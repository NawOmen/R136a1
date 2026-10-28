"""Read-only loopback preflight. A green result is NOT a complete demo acceptance."""
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect blocked", headers, fp)


def local_url(value):
    url = urllib.parse.urlsplit(value)
    if (url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
        raise argparse.ArgumentTypeError("Нужен локальный URL без пароля, пути и параметров")
    return value.rstrip("/")


def fetch(url, timeout, *, json_body=True):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Unexpected status")
        if not json_body:
            return None
        content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("Response too large")
        return json.loads(content)


def inspect(args, request=fetch):
    checks = []
    model = None
    for name, url in (("Авторизация", args.auth_url), ("Маркетплейс", args.marketplace_url), ("LLM Gateway", args.llm_url)):
        try:
            data = request(url + "/health", args.timeout)
            ok = isinstance(data, dict) and data.get("status") == "ok"
            if name == "LLM Gateway" and ok:
                model = data.get("local_model")
        except (OSError, ValueError):
            ok = False
        checks.append({"name": name, "passed": ok})
    for name, url in (("Страница входа", args.web_url + "/login"), ("Хранилище файлов", args.storage_url + "/minio/health/ready")):
        try:
            request(url, args.timeout, json_body=False)
            ok = True
        except (OSError, ValueError):
            ok = False
        checks.append({"name": name, "passed": ok})
    try:
        catalog = request(args.marketplace_url + "/api/v3/products", args.timeout)
        ok = isinstance(catalog, list) and len(catalog) > 0
    except (OSError, ValueError):
        ok = False
    checks.append({"name": "Непустой каталог из БД", "passed": ok})
    try:
        tags = request(args.ollama_url + "/api/tags", args.timeout)
        names = {item.get("name") for item in tags.get("models", []) if isinstance(item, dict)}
        ok = bool(model) and (model in names or (":" not in model and model + ":latest" in names))
    except (OSError, ValueError, AttributeError, TypeError):
        ok = False
    checks.append({"name": "Модель из конфигурации Gateway загружена в Ollama", "passed": ok})
    return {"scope": "Только доступность окружения. Не проверяет вход, допуск, генерацию, закупку или качество ИИ.",
            "infrastructure_passed": all(item["passed"] for item in checks), "checks": checks,
            "live_core_flow": "Не проверен: запустите final-core-flow.config.ts на отдельном синтетическом стенде"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option, port in (("web", 3000), ("auth", 8001), ("marketplace", 8002), ("llm", 8003), ("storage", 9000), ("ollama", 11434)):
        parser.add_argument(f"--{option}-url", type=local_url, default=f"http://localhost:{port}")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    if not 0 < args.timeout <= 30:
        parser.error("Таймаут должен быть больше нуля и не более 30 секунд")
    report = inspect(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["infrastructure_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

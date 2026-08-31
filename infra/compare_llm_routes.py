"""Сравнение Qwen и DeepSeek на одинаковых синтетических задачах этапа 4.

Скрипт не сохраняет ключ и не отправляет реальные данные. Без DEEPSEEK_API_KEY
выполняется только обязательный локальный маршрут.
"""

import json
import os
import time
import urllib.request

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
DEEPSEEK_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

TASKS = [
    "Извлеки JSON: нужны 5000 крафтовых стаканов 400 мл, PE, доставка Москва за 10 дней.",
    "Найди противоречие: в ТЗ 400 мл и PE, в старой накладной 350 мл и PLA.",
    "Предложи уточняющие вопросы, если не указаны количество, срок и город доставки.",
]


def post(url: str, payload: dict, headers: dict | None = None) -> tuple[float, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.load(response)
    return time.perf_counter() - started, json.dumps(body, ensure_ascii=False)


def main() -> None:
    print("Все задачи синтетические; реальные клиентские материалы не отправляются.")
    for number, task in enumerate(TASKS, start=1):
        local_time, local = post(
            f"{OLLAMA_URL.rstrip('/')}/api/chat",
            {
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": task}],
                "format": "json",
                "options": {"temperature": 0.1, "num_ctx": 8192},
            },
        )
        print(f"\nЗадача {number} | Qwen: {local_time:.2f} с\n{local[:1000]}")
        if not DEEPSEEK_API_KEY:
            print("DeepSeek: пропущен — ключ не настроен")
            continue
        external_time, external = post(
            f"{DEEPSEEK_URL.rstrip('/')}/chat/completions",
            {
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": task}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        )
        print(f"DeepSeek: {external_time:.2f} с\n{external[:1000]}")


if __name__ == "__main__":
    main()

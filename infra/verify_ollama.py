"""Проверка локальной LLM Qwen3.5 9B через Ollama и замер скорости генерации.

Запуск: python infra/verify_ollama.py
"""

import json
import time
import urllib.request

OLLAMA = "http://localhost:11434"


def get(path: str) -> dict:
    with urllib.request.urlopen(OLLAMA + path, timeout=30) as resp:
        return json.load(resp)


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def main() -> None:
    tags = get("/api/tags")
    print("Модели в Ollama:", [m["name"] for m in tags.get("models", [])])

    prompt = "Одним предложением ответь: что такое одноразовый бумажный стакан для горячих напитков?"
    started = time.time()
    result = post(
        "/api/generate",
        {"model": "qwen3.5:9b", "prompt": prompt, "stream": False},
    )
    elapsed = time.time() - started

    print("\nОтвет:", result.get("response", "").strip())
    print("\nОбщее время запроса: %.2f с" % elapsed)
    print("eval_count:", result.get("eval_count"))
    print("eval_duration (нс):", result.get("eval_duration"))

    if result.get("eval_count") and result.get("eval_duration"):
        tokens_per_sec = result["eval_count"] / (result["eval_duration"] / 1e9)
        print("Скорость генерации: %.1f токенов/с" % tokens_per_sec)


if __name__ == "__main__":
    main()

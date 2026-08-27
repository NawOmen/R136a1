"""Проверка локальной LLM Qwen3.5 9B через Ollama и замер производительности.

Измеряет:
- скорость генерации (ток/с) при холодном и прогретом запуске;
- TTFT (время до первого токена) в прогретом режиме;
- память модели через `ollama ps`;
- печатает команды для замера RAM/VRAM на основном компьютере (Linux + RTX 5060).

Запуск: python infra/verify_ollama.py
"""

import json
import time
import urllib.request

OLLAMA = "http://localhost:11434"
MODEL = "qwen3.5:9b"
PROMPT = "Одним предложением ответь: что такое одноразовый бумажный стакан для горячих напитков?"


def get(path: str) -> dict:
    with urllib.request.urlopen(OLLAMA + path, timeout=60) as resp:
        return json.load(resp)


def generate(prompt: str, stream: bool = False) -> dict:
    payload = json.dumps({"model": MODEL, "prompt": prompt, "stream": stream}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA + "/api/generate", data=payload, headers={"Content-Type": "application/json"}
    )
    started = time.time()
    first_token_at = None
    text_parts: list[str] = []
    eval_count = 0
    eval_duration = 0

    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            if not raw:
                continue
            obj = json.loads(raw.decode("utf-8"))
            if obj.get("response"):
                if first_token_at is None:
                    first_token_at = time.time()
                text_parts.append(obj["response"])
            if obj.get("done"):
                eval_count = int(obj.get("eval_count", 0))
                eval_duration = int(obj.get("eval_duration", 0))
                break

    total = time.time() - started
    ttft = (first_token_at - started) if first_token_at else None
    tokens_per_sec = (eval_count / (eval_duration / 1e9)) if eval_duration else None
    return {
        "text": "".join(text_parts),
        "total_s": total,
        "ttft_s": ttft,
        "eval_count": eval_count,
        "tokens_per_sec": tokens_per_sec,
    }


def main() -> None:
    tags = get("/api/tags")
    print("Модели в Ollama:", [m["name"] for m in tags.get("models", [])])

    print("\n[1] Холодный запуск (модель загружается в память)...")
    cold = generate(PROMPT, stream=True)
    print(f"  TTFT: {cold['ttft_s']:.2f} с | всего: {cold['total_s']:.2f} с | токенов: {cold['eval_count']}")
    if cold["tokens_per_sec"]:
        print(f"  скорость генерации (eval_duration): {cold['tokens_per_sec']:.1f} ток/с")

    print("\n[2] Память модели (ollama ps)...")
    ps = get("/api/ps")
    print(json.dumps(ps.get("models", []), ensure_ascii=False))

    print("\n[3] Прогретый запуск...")
    warm = generate(PROMPT, stream=True)
    print(f"  TTFT: {warm['ttft_s']:.2f} с | всего: {warm['total_s']:.2f} с | токенов: {warm['eval_count']}")
    if warm["tokens_per_sec"]:
        print(f"  скорость генерации (eval_duration): {warm['tokens_per_sec']:.1f} ток/с")

    print("\n=== Замер RAM/VRAM на основном компьютере (Linux + RTX 5060) ===")
    print("До загрузки модели:")
    print("  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader")
    print("  free -h")
    print("Во время генерации (в параллельном терминале):")
    print("  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader")
    print("  free -h")
    print("  ollama ps")


if __name__ == "__main__":
    main()

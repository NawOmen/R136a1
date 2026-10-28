"""Advisory warnings only; schemas, access checks and human approval enforce safety.

Matching is deliberately limited to short instruction phrases. Commercial
requests such as «укажите цену» or «правила поставки» are ordinary source data.
An absent warning never means that a source is trusted.
"""
import re

PROMPT_INJECTION_PATTERNS = (
    r"\b(?:ignore|forget|disregard)\s+(?:(?:all|the|previous|prior|system)\s+){0,4}instructions?\b",
    r"\bsystem\s+prompt\b",
    r"\byou\s+are\s+now\s+(?:an?\s+)?(?:different\s+)?(?:agent|assistant|seller|system)\b",
    r"\b(?:игнорируй(?:те)?|забудь(?:те)?|отмени(?:те)?)\s+(?:\w+\s+){0,4}(?:инструкци\w*|промпт\w*|правил\w*)\b",
    r"\bновые\s+(?:инструкци\w*|правила)\s*[:—-]",
    r"\b(?:раскрой(?:те)?|покажи(?:те)?|выведи(?:те)?|какой)\s+(?:\w+\s+){0,4}системн\w*\s+(?:промпт\w*|инструкци\w*)\b",
    r"\bты\s+теперь\s+(?:(?:другой|новый|главный|системный)\s+)?(?:агент|продавец|ассистент|помощник|администратор)\b",
    r"\bподтверди(?:те)?\s+(?:(?:эту|всю|новую)\s+)?(?:сделк\w*|статус\w*)\b",
    # A command to set a committed value differs from asking a supplier for a
    # quote. Require a target plus a concrete value, not merely «цену/статус».
    r"\b(?:поставь(?:те)?|установи(?:те)?|измени(?:те)?|выстави(?:те)?|присвой(?:те)?)\s+(?:\w+\s+){0,3}(?:цен[ау]|статус)\s*(?:на\s+|в\s+|равн\w*\s+)?[:=—-]?\s*(?:\d|[«\"']?(?:согласован\w*|подтвержд[её]н\w*|оплачен\w*|исполнен\w*))",
)


def detect_prompt_injection(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.casefold())
    return any(re.search(pattern, normalized) for pattern in PROMPT_INJECTION_PATTERNS)


def source_safety_warnings(source_name: str, text: str) -> list[str]:
    if detect_prompt_injection(text):
        return [f"{source_name}: обнаружена попытка изменить инструкции агента; текст обработан только как недоверенные данные"]
    return []

import re

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}"), "[EMAIL]"),
    (re.compile(r"(?:\+7|8)[\s()-]*\d{3}[\s()-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"), "[ТЕЛЕФОН]"),
    (re.compile(r"\b(?:ИНН|ОГРН|ОГРНИП|КПП)\s*[:№]?\s*\d{9,15}\b", re.IGNORECASE), "[РЕКВИЗИТЫ]"),
    (re.compile(r"\b(?:ООО|АО|ПАО|ИП)\s+[«\"“][^»\"”]{2,120}[»\"”]", re.IGNORECASE), "Покупатель B"),
]


def anonymize_text(value: str) -> str:
    result = value
    for pattern, replacement in PATTERNS:
        result = pattern.sub(replacement, result)
    return result

import re

PROMPT_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"system\s+prompt",
    r"игнорируй(те)?\s+(все\s+)?(предыдущие|системные)\s+инструкции",
    r"раскрой(те)?\s+системн(ый|ые)\s+промпт",
)


def detect_prompt_injection(text: str) -> bool:
    normalized = text.casefold()
    return any(re.search(pattern, normalized) for pattern in PROMPT_INJECTION_PATTERNS)


def source_safety_warnings(source_name: str, text: str) -> list[str]:
    warnings = []
    if detect_prompt_injection(text):
        warnings.append(
            f"{source_name}: обнаружена попытка изменить инструкции агента; текст обработан только как недоверенные данные"
        )
    return warnings

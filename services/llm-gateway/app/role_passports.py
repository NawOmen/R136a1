"""Паспорта агентных ролей, манифест моделей и реестр инструментов (этап S04).

Обычный код и OR-Tools указаны прямо: Coalition и Resilience не вызывают LLM.
Инструкция внутри недоверенного материала никогда не расширяет полномочия:
инструменты вызываются только кодом из фиксированного allowlist, а текст модели
не может добавить новый инструмент или изменить деньги/ресурс/сделку.
"""

from typing import Literal

PROMPT_VERSION = "buyer-extraction-1"
SELLER_PROMPT_VERSION = "seller-explain-1"
SCHEMA_VERSION = "buyer-evidence-1"
TASK_CONTRACT_VERSION = 1

Executor = Literal["model", "calculator", "human", "system"]
ToolKind = Literal["read", "write"]
ToolActor = Literal["model", "human", "system"]

ROLE_PASSPORTS: dict[str, dict] = {
    "buyer_investigation": {
        "title": "Buyer Investigation Agent",
        "purpose": "Восстановить проверяемую спецификацию потребности из недоверенных материалов покупателя.",
        "inputs": "Свободный текст, PDF, изображение, старый документ, голос (через локальную транскрипцию).",
        "outputs": "Категория, свойства с доказательствами, конфликты, уточняющие вопросы.",
        "sources": "Только загруженные покупателем материалы; оригиналы обрабатываются локально.",
        "tools": ["extract_document", "extract_image", "extract_audio", "extract_material",
                  "extract_requirements", "review_anonymized_facts"],
        "company_scope": "Покупатель видит только свои процессы; поиск исключает его компанию.",
        "prompt_version": PROMPT_VERSION,
        "model": "qwen3.5:9b (локально); внешний разбор — только обезличенные факты",
        "schema_version": SCHEMA_VERSION,
        "implemented_by": "model",
        "time_limits": "Локальный вызов до 180 c, внешний разбор до 45 c; текст ограничен max_combined_text_chars.",
        "resource_limits": "Не более 16 материалов, 25 МБ на файл, 100 МБ суммарно.",
        "stop_conditions": "Извлечение завершено; необязательный внешний разбор пропущен при недоступности; обязательное извлечение при сбое даёт failed, а не пустой успех.",
        "result": "BuyerAgentResult с доказательствами и версией извлечения.",
        "decision_by": "Покупатель подтверждает спецификацию вручную (human_approval).",
    },
    "buyer": {
        "title": "Buyer Agent",
        "purpose": "Оркестратор покупателя поверх расследования и программного подбора.",
        "inputs": "Подтверждённая спецификация потребности.",
        "outputs": "Подобранные производители с объяснением связи фактов и кандидатов.",
        "sources": "Восстановленные свойства, Capability Passport российских производителей.",
        "tools": ["search_capability_passports", "apply_user_clarification", "human_approval", "invalidate_source"],
        "company_scope": "Действия выполняются от компании-покупателя; смена компании не переносит чужой процесс.",
        "prompt_version": PROMPT_VERSION,
        "model": "qwen3.5:9b (локально)",
        "schema_version": SCHEMA_VERSION,
        "implemented_by": "model",
        "time_limits": "Наследует лимиты расследования; уточнения без ограничения по числу шагов, каждый шаг версионируется.",
        "resource_limits": "Только чтение каталога и паспортов; запись — лишь собственные ответы и согласия.",
        "stop_conditions": "Подтверждение покупателем либо отмена; неразрешённый конфликт блокирует подтверждение.",
        "result": "Подтверждённая версия требований для переноса в черновик потребности.",
        "decision_by": "Покупатель (каждое согласие содержит компанию, подписанта и версию условий).",
    },
    "seller": {
        "title": "Seller Agent",
        "purpose": "Объяснить, почему возможности производства подходят или не подходят запросу.",
        "inputs": "Capability Passport компании, категория, требования.",
        "outputs": "Признак соответствия, причины, текстовое объяснение.",
        "sources": "Паспорт компании-продавца; паспорт и запрос считаются недоверенными данными.",
        "tools": ["seller_explain"],
        "company_scope": "Требуется право can_sell компании; чужие паспорта недоступны.",
        "prompt_version": SELLER_PROMPT_VERSION,
        "model": "qwen3.5:9b (локально); при недоступности — rules_only без модели",
        "schema_version": "seller-explain-1",
        "implemented_by": "model",
        "time_limits": "Локальный вызов до 180 c; при сбое возвращается rules_only, а не выдуманное объяснение.",
        "resource_limits": "Только чтение собственного паспорта; цена и мощность не назначаются.",
        "stop_conditions": "Правила посчитали eligible; объяснение сформулировано либо заменено честной заглушкой.",
        "result": "SellerExplainOut: eligible, причины, объяснение, фактический маршрут.",
        "decision_by": "Производитель подтверждает публикацию и обязательства вручную.",
    },
    "marketplace": {
        "title": "Marketplace Agent",
        "purpose": "Сопоставить потребность с российскими производителями по обязательным фильтрам.",
        "inputs": "Категория и восстановленные свойства потребности.",
        "outputs": "Ранжированные кандидаты с причинами и предостережениями.",
        "sources": "Каталог товаров и Capability Passport; фильтры: RU, verified, can_sell.",
        "tools": ["search_capability_passports"],
        "company_scope": "Компания покупателя исключается из выдачи; контакты и бюджеты не раскрываются.",
        "prompt_version": "not-applicable",
        "model": "нет модели",
        "schema_version": SCHEMA_VERSION,
        "implemented_by": "code",
        "time_limits": "Синхронный SQL-запрос в рамках HTTP-запроса.",
        "resource_limits": "Только чтение каталога; два фиксированных параметризованных запроса.",
        "stop_conditions": "Фильтры применены; результат детерминирован.",
        "result": "Список CapabilityMatch с причинами.",
        "decision_by": "Покупатель выбирает предложение; агент решение не принимает.",
    },
    "coalition": {
        "title": "Coalition Agent",
        "purpose": "Проверить совместимость спроса и рассчитать экономику групповой партии.",
        "inputs": "Профили совместимости потребностей, MOQ, ценовые ступени, мощность.",
        "outputs": "Выполнимый расчёт группы и раздельные согласия участников.",
        "sources": "Подтверждённые карточки потребностей и групповые предложения.",
        "tools": [],
        "company_scope": "Каждый участник видит только собственные цену, срок и выгоду.",
        "prompt_version": "not-applicable",
        "model": "нет модели",
        "schema_version": "coalition-1",
        "implemented_by": "code",
        "time_limits": "Расчёт оптимизатора в ограниченном бюджете времени.",
        "resource_limits": "Только чтение потребностей и предложений.",
        "stop_conditions": "MOQ, мощность, совместимость и сроки подтверждены либо честно отказано.",
        "result": "Расчёт коалиции; обязательства возникают только после согласий всех сторон.",
        "decision_by": "Каждый покупатель и производитель подтверждают собственные условия.",
    },
    "resilience": {
        "title": "Resilience Agent",
        "purpose": "Построить сценарии N-1/N-2 и пересобрать сделку при сбое.",
        "inputs": "Основное распределение, резервы, пороги цены и срока.",
        "outputs": "Сценарии отказов с покрытием, доплатой, сроком и нужными решениями.",
        "sources": "Подтверждённые резервы и ресурсный учёт.",
        "tools": [],
        "company_scope": "Замена проходит тот же коммерческий и ресурсный контроль, что обычный заказ.",
        "prompt_version": "not-applicable",
        "model": "нет модели",
        "schema_version": "resilience-1",
        "implemented_by": "code",
        "time_limits": "Расчёт решателя в ограниченном бюджете времени; infeasible и timeout различаются.",
        "resource_limits": "Резерв используется только при подтверждении, TTL и доступном объёме.",
        "stop_conditions": "Непокрытый остаток честно показан, а не выдан за гарантию.",
        "result": "План замены с новой ревизией либо зафиксированный дефицит.",
        "decision_by": "Покупатель подтверждает замену при превышении порогов; в пределах порогов — предусмотренный переход.",
    },
}

MODEL_MANIFEST: dict[str, dict] = {
    "qwen3.5:9b": {
        "role": "Локальное извлечение, объяснения, справочник; оригиналы клиентских материалов не покидают контур.",
        "quality_gate": "Банк русскоязычных задач packages/test-fixtures/agent-task-bank: критичные поля, а не только валидный JSON.",
        "latency_budget": "До 180 c на вызов; фактическая задержка сохраняется в duration_ms каждого процесса.",
        "ram_vram": "Требования задаются картой развёртывания Ollama; gateway хранит только факт маршрута и длительность.",
        "license": "Семейство Qwen распространяется под Apache-2.0; точная редакция сверяется с картой дистрибутива модели при её смене.",
        "data_rule": "Оригиналы обрабатываются только локально; наружу уходят лишь обезличенные факты.",
    },
    "deepseek-v4-pro": {
        "role": "Необязательный внешний разбор обезличенных фактов для сложных наборов (3+ источника).",
        "quality_gate": "Тот же банк задач; внешний разбор не меняет значения, цены или статусы.",
        "latency_budget": "До 45 c на вызов; недоступность даёт возврат к локальной модели, а не пустой успех.",
        "ram_vram": "Внешний API; локальные ресурсы не требуются.",
        "license": "Коммерческий API по договору с провайдером; ключ не хранится в репозитории.",
        "data_rule": "Получает только сокращённый JSON фактов без исходного текста; стоимость без подтверждённого биллинга не оценивается.",
    },
}

TOOL_REGISTRY: dict[str, dict] = {
    "extract_document": {"kind": "read", "actors": ["model"], "roles": ["buyer_investigation"],
                         "schemas": ["SourceDescriptor"], "sources": "originals_local_only", "executor": "model"},
    "extract_image": {"kind": "read", "actors": ["model"], "roles": ["buyer_investigation"],
                      "schemas": ["SourceDescriptor"], "sources": "originals_local_only", "executor": "model"},
    "extract_audio": {"kind": "read", "actors": ["model"], "roles": ["buyer_investigation"],
                      "schemas": ["SourceDescriptor"], "sources": "originals_local_only", "executor": "model"},
    "extract_material": {"kind": "read", "actors": ["model"], "roles": ["buyer_investigation"],
                         "schemas": ["SourceDescriptor"], "sources": "originals_local_only", "executor": "model"},
    "extract_requirements": {"kind": "read", "actors": ["model"], "roles": ["buyer_investigation"],
                             "schemas": ["RawExtraction"], "sources": "originals_local_only", "executor": "model"},
    "review_anonymized_facts": {"kind": "read", "actors": ["model"], "roles": ["buyer_investigation"],
                                "schemas": ["ComplexReview"], "sources": "anonymized_facts_only", "executor": "model"},
    "search_capability_passports": {"kind": "read", "actors": ["model", "system"], "roles": ["buyer", "marketplace"],
                                    "schemas": ["CapabilityMatch"], "sources": "retrieval_filtered_ru_verified", "executor": "calculator"},
    "seller_explain": {"kind": "read", "actors": ["model", "system"], "roles": ["seller"],
                       "schemas": ["ExplanationDraft"], "sources": "own_passport_untrusted", "executor": "model"},
    "external_route_fallback": {"kind": "read", "actors": ["system"], "roles": ["buyer_investigation"],
                                "schemas": [], "sources": "none", "executor": "system"},
    "apply_user_clarification": {"kind": "write", "actors": ["human"], "roles": ["buyer"],
                                 "schemas": ["ClarificationIn"], "sources": "user_answer", "executor": "human"},
    "human_approval": {"kind": "write", "actors": ["human"], "roles": ["buyer"],
                       "schemas": ["RunRevisionIn"], "sources": "user_consent", "executor": "human"},
    "invalidate_source": {"kind": "write", "actors": ["human"], "roles": ["buyer"],
                          "schemas": ["RunRevisionIn"], "sources": "user_consent", "executor": "human"},
}

WRITE_TOOLS = {name for name, spec in TOOL_REGISTRY.items() if spec["kind"] == "write"}


ADAPTER_CONTRACT_VERSION = "external-adapter-1"

# S14.04: внешний сценарий не выбран — включённых адаптеров нет. Реестр задаёт
# границу расширения: версия контракта, разрешённые назначения, бюджет и флаг.
# Внутренний продукт работает без адаптера; сбой адаптера не пишет в домен.
EXTERNAL_ADAPTERS: dict[str, dict] = {}


def check_external_adapter(name: str, *, contract_version: str, scope: str, budget: float) -> Executor:
    """Серверная проверка внешнего адаптера: deny-by-default.

    Неизвестный, отключённый, чужой версии, вне назначений или сверх бюджета
    адаптер отклоняется до любого вызова. Private-контекст во внешний вызов
    не передаётся — только обезличенные факты (см. anonymizer).
    """
    spec = EXTERNAL_ADAPTERS.get(name)
    if spec is None or not spec.get("enabled", False):
        raise ValueError(f"Внешний адаптер «{name}» не зарегистрирован или отключён")
    if contract_version != ADAPTER_CONTRACT_VERSION or spec.get("contract_version") != ADAPTER_CONTRACT_VERSION:
        raise ValueError(f"Адаптер «{name}» несовместим с контрактом {ADAPTER_CONTRACT_VERSION}")
    if scope not in spec.get("scopes", frozenset()):
        raise ValueError(f"Назначение «{scope}» не разрешено адаптеру «{name}»")
    if not 0 < budget <= spec.get("max_budget", 0):
        raise ValueError(f"Бюджет вне лимита адаптера «{name}»")
    return "system"


SCENARIO_PERMISSIONS: dict[str, str] = {
    "buyer_investigation": "can_buy",
    "seller_explain": "can_sell",
    "marketplace_match": "can_buy",
    "coalition_build": "can_buy",
    "resilience_plan": "can_buy",
}

RUN_TYPE_PERMISSIONS: dict[str, str] = {
    "buyer_agent": "can_buy",
    "seller_agent": "can_sell",
}

SCENARIO_RUN_TYPES: dict[str, frozenset[str]] = {
    "buyer_investigation": frozenset({"buyer_agent"}),
    "seller_explain": frozenset({"seller_agent"}),
    "marketplace_match": frozenset({"buyer_agent"}),
    "coalition_build": frozenset({"buyer_agent"}),
    "resilience_plan": frozenset({"buyer_agent"}),
}


def check_tool_call(tool_name: str, actor: ToolActor) -> Executor:
    """Серверная проверка каждого вызова независимо от текста модели.

    Неизвестный инструмент отклоняется: модель не может добавить инструмент
    текстом. Модели доступны только read-инструменты; write-инструменты —
    только человеку через API с проверкой прав. Возвращает исполнителя для трассы.
    """
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        raise ValueError(f"Инструмент «{tool_name}» отсутствует в allowlist и запрещён")
    if actor not in spec["actors"]:
        raise ValueError(f"Инструмент «{tool_name}» недоступен исполнителю «{actor}»")
    if tool_name == "seller_explain" and actor == "system":
        # rules_only: правила уже посчитали eligible, модель не вызывалась.
        return "calculator"
    return spec["executor"]

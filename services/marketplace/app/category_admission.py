"""Категорийный допуск: обязательные доказательства и проверка применимости.

Модуль отвечает на вопрос «можно ли продавать этот товар» отдельно от вопроса
«проверена ли компания». Наличие поля сертификата не считается доказательством:
учитываются только документы, которые проверяющий человек подтвердил для нужной
области действия и срок которых не истёк.

Правила собраны обычным кодом. LLM не выдаёт допуск и не меняет статус документа.
Формулировки требований носят справочный характер и подлежат юридической проверке
перед эксплуатацией.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .experience import validate_characteristics
from .models import Document

RULES_VERSION = "categories-2"

# Статусы документа и требования для продавца и покупателя.
STATE_LABELS = {
    "satisfied": "Проверено человеком",
    "missing": "Не предоставлено",
    "uploaded_unverified": "Загружено, не проверено",
    "needs_scope": "Нужна проверка применимости",
    "rejected": "Не соответствует",
    "expired": "Данные проверки устарели",
    "scope_mismatch": "Документ относится к другой категории или подкатегории",
    "attribute_mismatch": "Документ не подтверждает характеристики товара",
}

UNSUPPORTED_STATE = "not_supported"
NOT_CONFIGURED_STATE = "not_configured"
NEEDS_CLASSIFICATION_STATE = "needs_classification"

# Характеристики, которые проверяющий обязан сопоставить с изделием.
CHARACTERISTIC_ALIASES: dict[str, tuple[str, ...]] = {
    "material": ("material", "материал", "body_material", "материал корпуса"),
    "coating": ("coating", "покрытие", "inner_coating", "внутреннее покрытие"),
    "purpose": ("purpose", "назначение", "temperature", "температурный режим"),
}

ATTRIBUTE_LABELS = {
    "material": "материал",
    "coating": "покрытие",
    "purpose": "назначение",
}


@dataclass(frozen=True)
class CategoryRequirement:
    code: str
    title: str
    legal_reference: str
    document_types: tuple[str, ...]
    seller_hint: str
    buyer_note: str
    blocking: bool = True
    # Атрибуты изделия, которые документ должен подтверждать.
    confirmable: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategoryProfile:
    key: str
    title: str
    categories: tuple[str, ...]
    requirements: tuple[CategoryRequirement, ...]
    subcategories: tuple[str, ...] | None = None
    supported: bool = True
    summary: str = ""
    advisories: tuple[str, ...] = ()
    documents_help: str = ""


@dataclass
class RequirementStatus:
    code: str
    title: str
    legal_reference: str
    blocking: bool
    state: str
    state_label: str
    seller_hint: str
    buyer_note: str
    document_ids: list[uuid.UUID] = field(default_factory=list)
    scope_note: str | None = None


@dataclass
class AdmissionReport:
    category: str
    subcategory: str | None
    state: str
    state_label: str
    supported: bool
    profile_title: str | None
    summary: str
    requirements: list[RequirementStatus]
    advisories: list[str]
    blocking_open: int
    checked_at: datetime
    profile_key: str | None = None
    rules_version: str = RULES_VERSION

    @property
    def blocking_requirements(self) -> list[RequirementStatus]:
        return [item for item in self.requirements if item.blocking and item.state != "satisfied"]

    @property
    def blocking_reasons(self) -> str:
        return "; ".join(
            f"{item.title} — {item.state_label.lower()}" for item in self.blocking_requirements
        )

    @property
    def blocking_message(self) -> str:
        """Нейтральная формулировка: её уточняет вызывающий путь (публикация, сделка, резерв)."""
        if not self.blocking_open:
            return "Обязательные доказательства подтверждены."
        reasons = self.blocking_reasons
        if reasons:
            return f"Допуск не подтверждён: {reasons}."
        return f"Допуск не подтверждён: {self.summary}"

    def as_payload(self) -> dict:
        return {
            "state": self.state,
            "supported": self.supported,
            "profile": self.profile_title,
            "profile_key": self.profile_key,
            "rules_version": self.rules_version,
            "blocking_open": self.blocking_open,
            "requirements": [
                {"code": item.code, "state": item.state, "documents": [str(doc) for doc in item.document_ids]}
                for item in self.requirements
            ],
        }


def normalize(value: str | None) -> str:
    """Сравнение категорий не должно зависеть от регистра, пробелов и буквы «ё»."""
    return (value or "").strip().lower().replace("ё", "е")


# ---------- Профили категорий ----------

PACKAGING_REQUIREMENTS = (
    CategoryRequirement(
        code="packaging_conformity",
        title="Подтверждение соответствия упаковки",
        legal_reference="ТР ТС 005/2011 «О безопасности упаковки»: тип подтверждения определяется "
        "применимостью к конкретному изделию и проверяется человеком",
        document_types=("declaration", "certificate"),
        seller_hint="Загрузите действующее подтверждение соответствия и укажите область действия: "
        "категорию и подкатегорию изделия.",
        buyer_note="У продавца проверено подтверждение соответствия упаковки по ТР ТС 005/2011.",
    ),
    CategoryRequirement(
        code="food_contact",
        title="Материал и покрытие, контактирующие с продукцией",
        legal_reference="ТР ТС 005/2011: требования к упаковке, контактирующей с пищевой продукцией",
        document_types=("test_report", "declaration", "certificate"),
        seller_hint="Нужен документ о материале и внутреннем покрытии. Проверяющий фиксирует, "
        "какие материал и покрытие подтверждены.",
        buyer_note="Проверен документ о контакте с пищевой продукцией. Соответствие конкретной "
        "партии проверяется при приёмке.",
        confirmable=("material", "coating"),
    ),
)

PACKAGING_ADVISORIES = (
    "Маркировка единым знаком обращения «ЕАС» наносится на упаковку или сопроводительный документ.",
    "Укажите назначение изделия: горячие или холодные напитки, а также условия эксплуатации.",
)

PROFILES: tuple[CategoryProfile, ...] = (
    # Демонстрационная категория: путь выбора категории и подкатегории в каталоге.
    CategoryProfile(
        key="paper_cups",
        title="Бумажные стаканы и пищевая упаковка",
        categories=("упаковка и тара",),
        subcategories=("бумажные стаканы",),
        summary="Упаковка, контактирующая с пищевой продукцией. Требуются подтверждение соответствия "
        "и документ о материале и покрытии.",
        requirements=PACKAGING_REQUIREMENTS,
        advisories=PACKAGING_ADVISORIES,
        documents_help="Загрузите декларацию или сертификат и протокол испытаний. Укажите категорию "
        "«Упаковка и тара» и подкатегорию «Бумажные стаканы».",
    ),
    # Совместимость с товарами, у которых категория задана точным названием товара.
    CategoryProfile(
        key="paper_cups_by_title",
        title="Бумажные стаканы и пищевая упаковка",
        categories=("бумажные стаканы", "пищевая упаковка"),
        summary="Категория распознана по названию товара. Требования те же, что для пищевой упаковки.",
        requirements=PACKAGING_REQUIREMENTS,
        advisories=PACKAGING_ADVISORIES,
        documents_help="Загрузите декларацию или сертификат и протокол испытаний, указав область "
        "действия — вид продукции.",
    ),
    CategoryProfile(
        key="packaging_other",
        title="Прочая упаковка и тара",
        categories=("упаковка и тара",),
        summary="Общие требования безопасности упаковки без подтверждённого контакта с пищевой продукцией.",
        requirements=(
            CategoryRequirement(
                code="packaging_conformity",
                title="Подтверждение соответствия упаковки",
                legal_reference="ТР ТС 005/2011 «О безопасности упаковки»",
                document_types=("declaration", "certificate"),
                seller_hint="Загрузите действующее подтверждение соответствия и укажите область действия.",
                buyer_note="У продавца проверено подтверждение соответствия упаковки.",
            ),
        ),
        advisories=("Если упаковка контактирует с пищей, нужен отдельный документ о материале и покрытии.",),
    ),
    CategoryProfile(
        key="food_products",
        title="Продукты питания",
        categories=("продукты питания",),
        summary="Пищевая продукция: подтверждение безопасности и корректная маркировка.",
        requirements=(
            CategoryRequirement(
                code="food_safety",
                title="Подтверждение безопасности пищевой продукции",
                legal_reference="ТР ТС 021/2011 «О безопасности пищевой продукции», ТР ТС 022/2011 "
                "(маркировка)",
                document_types=("declaration", "certificate"),
                seller_hint="Загрузите декларацию или свидетельство о государственной регистрации "
                "и укажите область действия.",
                buyer_note="У продавца проверено подтверждение безопасности пищевой продукции.",
            ),
        ),
        advisories=(
            "Укажите срок годности и условия хранения: скоропортящаяся продукция требует "
            "подтверждённого температурного режима доставки.",
            "Для продукции животного происхождения может потребоваться ветеринарный сопроводительный документ.",
        ),
    ),
    CategoryProfile(
        key="electronics",
        title="Электроника и оборудование",
        categories=("электроника", "оборудование"),
        summary="Технические изделия: подтверждение соответствия и условия гарантии.",
        requirements=(
            CategoryRequirement(
                code="tech_conformity",
                title="Подтверждение соответствия технического изделия",
                legal_reference="Применимые технические регламенты ЕАЭС; конкретный регламент "
                "определяет проверяющий",
                document_types=("declaration", "certificate"),
                seller_hint="Загрузите подтверждение соответствия и укажите, к какой продукции оно относится.",
                buyer_note="У продавца проверено подтверждение соответствия изделия.",
            ),
        ),
        advisories=("Зафиксируйте гарантийные условия, пусконаладку и сервис отдельно от цены товара.",),
    ),
    CategoryProfile(
        key="construction_finishing",
        title="Отделочные материалы",
        categories=("строительство",),
        subcategories=("отделочные материалы",),
        summary="Отделочные материалы: пожарная безопасность и гигиенические требования.",
        requirements=(
            CategoryRequirement(
                code="fire_safety",
                title="Подтверждение пожарной безопасности",
                legal_reference="Применимые технические регламенты о требованиях пожарной безопасности; "
                "область действия подтверждает проверяющий",
                document_types=("certificate", "declaration", "test_report"),
                seller_hint="Загрузите сертификат или протокол испытаний с указанием класса и области применения.",
                buyer_note="У продавца проверен документ о пожарной безопасности материала.",
            ),
        ),
    ),
    CategoryProfile(
        key="personal_protection",
        title="Средства защиты и гигиеническая продукция",
        categories=("медицина и гигиена",),
        subcategories=("средства защиты", "гигиеническая продукция"),
        summary="Изделия для защиты и гигиены: подтверждение соответствия применимому регламенту.",
        requirements=(
            CategoryRequirement(
                code="protection_conformity",
                title="Подтверждение соответствия изделия",
                legal_reference="Применимые технические регламенты ЕАЭС; тип подтверждения определяет "
                "проверяющий",
                document_types=("declaration", "certificate"),
                seller_hint="Загрузите подтверждение соответствия с указанием вида изделия.",
                buyer_note="У продавца проверено подтверждение соответствия изделия.",
            ),
        ),
    ),
    # Контролируемое ограничение: прототип не берётся продавать медизделия и лекарства.
    CategoryProfile(
        key="medical_unsupported",
        title="Медицинские изделия и лекарственные средства",
        categories=("медицина и гигиена",),
        subcategories=("расходные материалы",),
        supported=False,
        summary="Прототип не публикует медицинские изделия и лекарственные средства: для категории нужны "
        "регистрационные документы, лицензии и условия хранения, которых в демонстрационном профиле нет.",
        requirements=(),
        advisories=(
            "Если товар не является медицинским изделием, укажите другую подкатегорию и приложите документы.",
        ),
    ),
    CategoryProfile(
        key="medical_by_title",
        title="Медицинские изделия и лекарственные средства",
        categories=("медикаменты", "лекарственные средства", "медицинские изделия"),
        supported=False,
        summary="Категория распознана по названию товара. Прототип не публикует лекарства и медицинские "
        "изделия: нужен отдельный профиль требований, лицензии и проверка условий хранения.",
        requirements=(),
    ),
)


def match_profile(category: str, subcategory: str | None) -> CategoryProfile | None:
    """Найти профиль категории: точное совпадение подкатегории важнее общего правила категории."""
    norm_category = normalize(category)
    norm_subcategory = normalize(subcategory)
    best: CategoryProfile | None = None
    best_score = 0
    for profile in PROFILES:
        subcategories = profile.subcategories or ()
        score = 0
        if norm_category in profile.categories and norm_subcategory and norm_subcategory in subcategories:
            score = 5  # категория и подкатегория совпали точно
        elif norm_subcategory and norm_subcategory in profile.categories:
            score = 4  # подкатегория указана как отдельное название товара
        elif norm_category in profile.categories and profile.subcategories is None:
            score = 3  # правило уровня категории
        elif norm_category in subcategories:
            score = 2  # товар назван точным именем вместо ветки каталога
        if score > best_score:
            best, best_score = profile, score
    return best


def classification_hint(category: str) -> str | None:
    """Категории, где правило зависит от подкатегории, нельзя оценивать без классификации."""
    name = normalize(category)
    if not name:
        return None
    has_subcategory_rules = any(
        name in profile.categories and profile.subcategories for profile in PROFILES
    )
    has_category_rule = any(
        name in profile.categories and not profile.subcategories for profile in PROFILES
    )
    if has_subcategory_rules and not has_category_rule:
        return (
            "Правила этой категории зависят от вида товара. Укажите подкатегорию, чтобы система "
            "проверила применимые требования; без классификации допуск не выдаётся."
        )
    return None


def _parent_category(name: str) -> str | None:
    """Родительская категория для названия, которое используется как подкатегория каталога."""
    for profile in PROFILES:
        if name in (profile.subcategories or ()) and profile.categories:
            return profile.categories[0]
    return None


def canonical_scope(category: str | None, subcategory: str | None) -> tuple[str, str | None]:
    """Привести область к уровням «категория / подкатегория».

    Товар может быть назван точным именем вместо ветки каталога: тогда название
    считается подкатегорией, а родитель берётся из профилей.
    """
    norm_category = normalize(category)
    norm_subcategory = normalize(subcategory)
    if norm_subcategory:
        return norm_category, norm_subcategory
    parent = _parent_category(norm_category) if norm_category else None
    if parent:
        return parent, norm_category
    return norm_category, None


def characteristic_value(characteristics: dict | None, attribute: str) -> str | None:
    normalized = {normalize(str(key)): value for key, value in (characteristics or {}).items()}
    for alias in CHARACTERISTIC_ALIASES.get(attribute, (attribute,)):
        value = normalized.get(normalize(alias))
        if value not in (None, ""):
            return str(value)
    return None


def _values_relate(product_value: str, confirmed_value: str) -> bool:
    """Подтверждённое значение должно совпадать со значением товара или входить в него."""
    product = normalize(product_value)
    confirmed = normalize(confirmed_value)
    if not product or not confirmed:
        return False
    return product == confirmed or confirmed in product or product in confirmed


def _document_scope_values(document: Document) -> tuple[str, str | None]:
    return normalize(document.scope_category), normalize(document.scope_subcategory)


def _has_scope(document: Document) -> bool:
    category, subcategory = _document_scope_values(document)
    return bool(category or subcategory)


def document_applies_to(
    document: Document, product_scope: tuple[str, str | None]
) -> tuple[bool, str | None]:
    """Структурная проверка применимости документа к товару.

    Совпадения только по общей категории недостаточно, если обе подкатегории указаны
    и различаются. Широкое применение (документ без подкатегории) — это явное решение
    проверяющего, потому что область действия фиксирует именно он.
    """
    if not _has_scope(document):
        return False, None
    document_scope = canonical_scope(document.scope_category, document.scope_subcategory)
    product_category, product_subcategory = product_scope
    if not document_scope[0] or not product_category:
        return False, None
    if document_scope[0] != product_category:
        return False, None
    if document_scope[1] is None:
        return True, None
    if product_subcategory is None:
        return True, (
            f"Подкатегория товара не указана: документ подтверждён для «{document.scope_subcategory}». "
            "Проверьте применимость к своей спецификации."
        )
    if document_scope[1] == product_subcategory:
        return True, None
    return False, None


def _is_expired(document: Document, today: date) -> bool:
    return document.valid_until is not None and document.valid_until < today


def _ids(documents: list[Document]) -> list[uuid.UUID]:
    return [document.id for document in documents]


def _coverage_state(
    requirement: CategoryRequirement,
    documents: list[Document],
    characteristics: dict | None,
) -> tuple[str | None, str | None]:
    """Проверить, подтверждает ли документ характеристики изделия."""
    for attribute in requirement.confirmable:
        product_value = characteristic_value(characteristics, attribute)
        if not product_value:
            continue
        confirmed = [
            str(value)
            for document in documents
            for value in (document.confirms or {}).get(attribute, [])
        ]
        if confirmed and not any(_values_relate(product_value, value) for value in confirmed):
            label = ATTRIBUTE_LABELS.get(attribute, attribute)
            return "attribute_mismatch", (
                f"Документ подтверждает {label}: {', '.join(sorted(set(confirmed)))}; "
                f"у товара указано «{product_value}». Нужен документ на этот материал или покрытие."
            )
    return None, None


def _unconfirmed_advisories(
    requirements: tuple[CategoryRequirement, ...],
    documents: list[Document],
    characteristics: dict | None,
) -> list[str]:
    """Предупреждения: характеристика указана, но проверяющий её не зафиксировал."""
    advisories: list[str] = []
    for requirement in requirements:
        for attribute in requirement.confirmable:
            product_value = characteristic_value(characteristics, attribute)
            if not product_value:
                continue
            confirmed = [
                str(value)
                for document in documents
                for value in (document.confirms or {}).get(attribute, [])
            ]
            if not confirmed:
                label = ATTRIBUTE_LABELS.get(attribute, attribute)
                advisories.append(
                    f"Проверяющий не зафиксировал подтверждённые значения для «{label}»: "
                    f"у товара указано «{product_value}». Уточните применимость при новом обязательстве."
                )
    return advisories


def _requirement_state(
    requirement: CategoryRequirement,
    documents: list[Document],
    product_scope: tuple[str, str | None],
    today: date,
    characteristics: dict | None,
) -> tuple[str, list[uuid.UUID], str | None]:
    """Определить состояние требования по документам компании."""
    candidates = [document for document in documents if document.document_type in requirement.document_types]
    if not candidates:
        return "missing", [], None
    scoped = [document for document in candidates if _has_scope(document)]
    unscoped = [document for document in candidates if not _has_scope(document)]
    matched: list[Document] = []
    scope_note: str | None = None
    for document in scoped:
        applies, note = document_applies_to(document, product_scope)
        if applies:
            matched.append(document)
            scope_note = scope_note or note
    if not matched:
        if unscoped:
            return "needs_scope", _ids(unscoped), None
        return "scope_mismatch", _ids(scoped), None

    fresh = [
        document
        for document in matched
        if document.verification_status == "verified" and not _is_expired(document, today)
    ]
    if fresh:
        coverage_state, coverage_note = _coverage_state(requirement, fresh, characteristics)
        if coverage_state:
            return coverage_state, _ids(fresh), coverage_note
        return "satisfied", _ids(fresh), scope_note
    # Порядок объяснений: ждём решения проверяющего → документ отклонён → срок истёк.
    pending = [document for document in matched if document.verification_status == "unverified"]
    if pending:
        return "uploaded_unverified", _ids(pending), scope_note
    rejected = [document for document in matched if document.verification_status == "rejected"]
    if rejected:
        return "rejected", _ids(rejected), scope_note
    expired = [document for document in matched if document.verification_status == "verified"]
    if expired:
        return "expired", _ids(expired), scope_note
    return "uploaded_unverified", _ids(matched), scope_note


def evaluate_admission(
    *,
    category: str,
    subcategory: str | None,
    characteristics: dict,
    documents: list[Document],
    moq_units: int = 1,
    today: date | None = None,
) -> AdmissionReport:
    """Оценить допуск товара по документам компании."""
    today = today or datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    profile = match_profile(category, subcategory)
    if profile is None:
        hint = classification_hint(category)
        if hint is not None:
            return AdmissionReport(
                category=category,
                subcategory=subcategory,
                state=NEEDS_CLASSIFICATION_STATE,
                state_label="Нужна классификация товара",
                supported=True,
                profile_title=None,
                summary=hint,
                requirements=[],
                advisories=[
                    "Если товар не относится к ограниченным позициям, укажите подкатегорию и приложите документы.",
                ],
                blocking_open=1,
                checked_at=now,
            )
        return AdmissionReport(
            category=category,
            subcategory=subcategory,
            state=NOT_CONFIGURED_STATE,
            state_label="Обязательные доказательства не заданы",
            supported=True,
            profile_title=None,
            summary="Для этой категории обязательные доказательства в прототипе не заданы. "
            "Допуск опирается на проверку компании; при необходимости правила уточняются.",
            requirements=[],
            advisories=[],
            blocking_open=0,
            checked_at=now,
        )

    if not profile.supported:
        return AdmissionReport(
            category=category,
            subcategory=subcategory,
            state=UNSUPPORTED_STATE,
            state_label="Категория не поддерживается",
            supported=False,
            profile_title=profile.title,
            profile_key=profile.key,
            summary=profile.summary,
            requirements=[],
            advisories=list(profile.advisories),
            blocking_open=1,
            checked_at=now,
        )

    product_scope = canonical_scope(category, subcategory)
    requirement_states: list[RequirementStatus] = []
    for requirement in profile.requirements:
        state, document_ids, scope_note = _requirement_state(
            requirement, documents, product_scope, today, characteristics
        )
        requirement_states.append(
            RequirementStatus(
                code=requirement.code,
                title=requirement.title,
                legal_reference=requirement.legal_reference,
                blocking=requirement.blocking,
                state=state,
                state_label=STATE_LABELS[state],
                seller_hint=requirement.seller_hint,
                buyer_note=requirement.buyer_note,
                document_ids=document_ids,
                scope_note=scope_note,
            )
        )

    _, characteristic_warnings = validate_characteristics(category, subcategory, characteristics, moq_units)
    confirmed_documents = [
        document
        for document in documents
        if document.verification_status == "verified" and not _is_expired(document, today)
    ]
    advisories = (
        list(profile.advisories)
        + characteristic_warnings
        + _unconfirmed_advisories(profile.requirements, confirmed_documents, characteristics)
    )
    blocking_open = sum(
        1 for item in requirement_states if item.blocking and item.state != "satisfied"
    )
    if blocking_open:
        state, state_label = "blocked", "Обязательства заблокированы"
    else:
        state, state_label = "admitted", "Допуск подтверждён"
    return AdmissionReport(
        category=category,
        subcategory=subcategory,
        state=state,
        state_label=state_label,
        supported=True,
        profile_title=profile.title,
        profile_key=profile.key,
        summary=profile.summary,
        requirements=requirement_states,
        advisories=advisories,
        blocking_open=blocking_open,
        checked_at=now,
    )

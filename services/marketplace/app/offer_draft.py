"""Черновик коммерческого предложения из подтверждённых данных продавца.

Значения считает обычный код: цена и ступени берутся из каталога, срок и MOQ из
товара или паспорта возможностей, доступный объём — из остатка склада и
календаря мощностей. LLM не назначает цену и не подтверждает мощность; модель
может только объяснить результат, и это делается отдельным вызовом.

Каждое поле черновика сопровождается источником, чтобы продавец видел, на чём
основано значение, и осознанно его подтверждал.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .money import decimal
from .category_admission import normalize
from .matching import order_unit
from .models import CapacityEntry, CapabilityPassport, Need, Product


@dataclass
class DraftField:
    name: str
    label: str
    value: Decimal | float | int | None
    source: str
    confirmed: bool
    note: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "value": self.value,
            "source": self.source,
            "confirmed": self.confirmed,
            "note": self.note,
        }


@dataclass
class OfferDraftResult:
    price_rub: Decimal | None
    available_units: int | None
    moq_units: int | None
    lead_time_days: int | None
    delivery_cost_rub: Decimal | None
    price_tiers: list[dict] = field(default_factory=list)
    fields: list[DraftField] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    explanation: str = ""
    product_id: str | None = None
    resource_kind: str = "capacity"
    source_updated_at: str | None = None
    need_revision: int = 1

    def payload(self) -> dict:
        return {
            "product_id": self.product_id,
            "resource_kind": self.resource_kind,
            "source_updated_at": self.source_updated_at,
            "need_revision": self.need_revision,
            "price_rub": self.price_rub,
            "available_units": self.available_units,
            "moq_units": self.moq_units,
            "lead_time_days": self.lead_time_days,
            "delivery_cost_rub": self.delivery_cost_rub,
            "price_tiers": self.price_tiers,
        }


# Only explicit semantic aliases are equivalent. Units and ranges are never guessed.
_CHARACTERISTIC_KEYS = {
    "объём": "volume_ml", "объем": "volume_ml", "объём, мл": "volume_ml",
    "материал": "material", "покрытие": "coating", "назначение": "purpose",
    "цвет": "color", "размер": "size", "единица измерения": "unit",
}


def _characteristic_value(value):
    if isinstance(value, str):
        return " ".join(normalize(value).split())
    # Preserve types of compound specifications: [10, 20] is not a scalar range.
    if isinstance(value, list):
        return [_characteristic_value(item) for item in value]
    if isinstance(value, dict):
        return {normalize(str(key)): _characteristic_value(item) for key, item in value.items()}
    return value


def _characteristics(values: dict | None) -> dict[str, list]:
    result: dict[str, list] = {}
    for key, value in (values or {}).items():
        key = normalize(str(key))
        key = _CHARACTERISTIC_KEYS.get(key, key)
        if key == "unit" and normalize(str(value)) in {"шт.", "штука", "штуки", "штук"}:
            value = "шт"
        result.setdefault(key, []).append(_characteristic_value(value))
    result.setdefault("unit", ["шт"])  # Legacy unlabelled quantities are pieces, never packages.
    return result


def _matches_need(product: Product, need: Need) -> tuple[bool, str]:
    from .category_compatibility import compare_specifications
    result = compare_specifications(product, need)
    return result.matches, result.reason


def _tier_price(product: Product, volume: int, unit: str) -> tuple[Decimal, str]:
    """Цена за единицу с учётом ступеней: берём лучшую подходящую ступень."""
    price = decimal(product.price_rub)
    source = "товар каталога: базовая цена"
    for tier in sorted(product.price_tiers or [], key=lambda item: item.get("min_units", 0)):
        try:
            min_units = int(tier.get("min_units") or 0)
            unit_price = decimal(tier.get("unit_price_rub") or 0)
        except (TypeError, ValueError):
            continue
        if unit_price > 0 and volume >= min_units:
            price = unit_price
            source = f"товар каталога: ступень от {min_units} {unit}"
    return price, source


async def build_offer_draft(
    *,
    need: Need,
    products: list[Product],
    passport: CapabilityPassport | None,
    capacity_units: int,
    today: date | None = None,
    stock_by_product: dict | None = None,
) -> OfferDraftResult:
    """Собрать черновик КП: значения, источники, пробелы и предупреждения."""
    today = today or date.today()
    fields: list[DraftField] = []
    missing: list[str] = []
    warnings: list[str] = []

    matching = [(product, _matches_need(product, need)) for product in products]
    suitable = [product for product, (matches, _) in matching if matches]
    for product, (matches, reason) in matching:
        if not matches:
            warnings.append(f"Товар «{product.name}» не использован: {reason}.")

    requested_volume = int(need.volume_units)
    unit = str((need.characteristics or {}).get("unit") or "шт").strip()
    stock_sources: list[str] = []
    stock_total = 0
    # One SKU supplies both price and stock; never sum unlike products.
    for product in suitable[:1]:
        quantity = stock_by_product.get(product.id, 0) if stock_by_product is not None else product.stock_units
        if quantity:
            stock_total = int(quantity)
            stock_sources.append(f"свободный остаток «{product.name}»: {quantity} {unit}")

    business_kind = "manufacturer"
    if passport is not None:
        business_kind = str((passport.details or {}).get("business_kind") or "manufacturer")

    if business_kind == "stock_supplier":
        available = stock_total or None
        source = "; ".join(stock_sources) or "остаток склада не заполнен"
        if not available:
            missing.append("Остаток склада не заполнен: укажите наличие товара")
    elif business_kind == "both":
        available = stock_total or capacity_units or None
        source = "; ".join(stock_sources) if stock_total else f"свободная мощность к сроку: {capacity_units} {unit}"
        if available is None:
            missing.append("Нет ни остатка, ни подтверждённой мощности к сроку")
    else:
        available = capacity_units or None
        source = f"календарь мощностей до срока: {capacity_units} {unit}" if capacity_units else "мощность к сроку не заполнена"
        if not available:
            missing.append("Не заполнена доступная мощность к сроку потребности")

    if available is not None and available < requested_volume:
        warnings.append(
            f"Доступный объём {available} {unit} меньше запрошенных {requested_volume} {unit}: "
            "укажите реально доступный объём или откажитесь от предложения."
        )
    fields.append(
        DraftField(
            name="available_units",
            label=f"Доступный объём, {unit}",
            value=available,
            source=source,
            confirmed=available is not None,
            note=None if available is not None else "Заполните вручную",
        )
    )

    if suitable:
        product = suitable[0]
        price, price_source = _tier_price(product, requested_volume, unit)
        fields.append(
            DraftField(
                name="price_rub",
                label="Цена за единицу, ₽",
                value=price,
                source=price_source,
                confirmed=True,
                note=f"Товар «{product.name}»",
            )
        )
        price_tiers = [dict(item) for item in (product.price_tiers or [])]
        moq = int(product.moq_units)
        moq_source = f"товар каталога «{product.name}»"
        lead_time = int(product.lead_time_days)
        lead_source = f"товар каталога «{product.name}»"
        if len(suitable) > 1:
            warnings.append(
                "Подходит несколько товаров: проверьте, что выбранные характеристики и цена соответствуют заказу."
            )
    else:
        price = None
        price_tiers = []
        fields.append(
            DraftField(
                name="price_rub",
                label="Цена за единицу, ₽",
                value=None,
                source="нет подходящего товара каталога",
                confirmed=False,
                note="Цену назначает человек: агент не устанавливает цену",
            )
        )
        missing.append("Нет товара каталога с подходящей категорией и характеристиками: укажите цену вручную")

        from .matching import passport_scope_limits
        moq = passport_scope_limits(passport,need.category,need.characteristics,need.subcategory)[0] if passport else None
        moq_source = "паспорт возможностей: минимальный заказ"
        lead_time = None
        lead_source = "не задано"

    fields.append(
        DraftField(
            name="moq_units",
            label=f"MOQ предложения, {unit}",
            value=moq,
            source=moq_source,
            confirmed=moq is not None,
            note=None if moq is not None else "Заполните вручную",
        )
    )
    if moq is None:
        missing.append("Минимальный заказ не задан ни в товаре, ни в паспорте возможностей")

    fields.append(
        DraftField(
            name="lead_time_days",
            label="Срок производства, дней",
            value=lead_time,
            source=lead_source,
            confirmed=lead_time is not None,
            note=None if lead_time is not None else "Срок производства указывает человек",
        )
    )
    if lead_time is None:
        missing.append("Срок производства не задан: укажите его вручную")

    # Логистику агент не считает: тариф зависит от перевозчика и условий покупателя.
    fields.append(
        DraftField(
            name="delivery_cost_rub",
            label="Логистика, ₽",
            value=None,
            source="стоимость доставки не рассчитывается автоматически",
            confirmed=False,
            note="Укажите стоимость доставки или 0, если забирает покупатель",
        )
    )
    missing.append("Стоимость логистики указывает человек")

    if capacity_units and available is not None and capacity_units > 0 and available < capacity_units:
        warnings.append(
            "Доступный объём ограничен остатком склада и меньше подтверждённой мощности: "
            "проверьте, успеете ли произвести остаток к сроку."
        )

    deadline_days = max(0, (need.deadline_date - today).days)
    if lead_time is not None and lead_time > deadline_days:
        warnings.append(
            f"Срок производства {lead_time} дней превышает срок потребности {deadline_days} дней: "
            "предложение будет отклонено при выборе."
        )

    confirmed_fields = [item.label for item in fields if item.confirmed]
    explanation = (
        "Черновик подготовлен по данным компании: "
        + (", ".join(confirmed_fields) if confirmed_fields else "подтверждённых значений нет")
        + ". Цена и объём не назначаются автоматически без источника: перед отправкой проверьте "
        "значения и заполните то, что помечено как требующее решения человека."
    )
    chosen = suitable[0] if suitable else None
    return OfferDraftResult(
        product_id=str(chosen.id) if chosen and chosen.id else None,
        resource_kind="stock" if business_kind == "stock_supplier" or (business_kind == "both" and stock_total) else "capacity",
        source_updated_at=chosen.updated_at.isoformat() if chosen and chosen.updated_at else None,
        need_revision=need.revision or 1,
        price_rub=price,
        available_units=available,
        moq_units=moq,
        lead_time_days=lead_time,
        delivery_cost_rub=None,
        price_tiers=price_tiers,
        fields=fields,
        missing=missing,
        warnings=warnings,
        explanation=explanation,
    )


def available_capacity_units(entries: list[CapacityEntry], need: Need, today: date | None = None) -> int:
    """Свободная мощность к сроку потребности из календаря мощностей."""
    today = today or date.today()
    from .resource_scopes import conversion_for
    total = 0
    for entry in entries:
        if not today <= entry.date <= need.deadline_date: continue
        conversion = conversion_for(entry,need.category,need.subcategory,order_unit(need.characteristics))
        if conversion is not None: total += int(entry.available_units) // conversion['resource_units_per_order_unit']
    return total



def changed_fields(draft_payload: dict, offer_values: dict) -> list[str]:
    """Какие поля человек изменил относительно черновика."""
    changed: list[str] = []
    for name, value in offer_values.items():
        original = draft_payload.get(name)
        if original is None and value in (None, 0, 0.0):
            continue
        if isinstance(value, float) or isinstance(original, float):
            try:
                if original is not None and abs(decimal(original) - decimal(value or 0)) < decimal("0.01"):
                    continue
            except (TypeError, ValueError):
                pass
        if original != value:
            changed.append(name)
    return changed

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

from .category_admission import normalize
from .models import CapacityEntry, CapabilityPassport, Need, Product


@dataclass
class DraftField:
    name: str
    label: str
    value: float | int | None
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
    price_rub: float | None
    available_units: int | None
    moq_units: int | None
    lead_time_days: int | None
    delivery_cost_rub: float | None
    price_tiers: list[dict] = field(default_factory=list)
    fields: list[DraftField] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    explanation: str = ""

    def payload(self) -> dict:
        return {
            "price_rub": self.price_rub,
            "available_units": self.available_units,
            "moq_units": self.moq_units,
            "lead_time_days": self.lead_time_days,
            "delivery_cost_rub": self.delivery_cost_rub,
            "price_tiers": self.price_tiers,
        }


def _product_volume(characteristics: dict | None) -> str:
    return str((characteristics or {}).get("volume_ml") or (characteristics or {}).get("объём") or "")


def _matches_need(product: Product, need: Need) -> tuple[bool, str]:
    """Товар подходит, если совпадает категория и объём изделия (когда он указан)."""
    product_category = normalize(product.category)
    need_category = normalize(need.category)
    if product_category != need_category:
        product_name = normalize(product.subcategory or "")
        if product_category and product_category not in need_category and need_category != product_name:
            return False, "категория товара не совпадает с потребностью"
    need_volume = _product_volume(need.characteristics)
    product_volume = _product_volume(product.characteristics)
    if need_volume and product_volume and normalize(need_volume) != normalize(product_volume):
        return False, "объём изделия отличается от указанного в потребности"
    return True, ""


def _tier_price(product: Product, volume: int) -> tuple[float, str]:
    """Цена за единицу с учётом ступеней: берём лучшую подходящую ступень."""
    price = float(product.price_rub)
    source = "товар каталога: базовая цена"
    for tier in sorted(product.price_tiers or [], key=lambda item: item.get("min_units", 0)):
        try:
            min_units = int(tier.get("min_units") or 0)
            unit_price = float(tier.get("unit_price_rub") or 0)
        except (TypeError, ValueError):
            continue
        if unit_price > 0 and volume >= min_units:
            price = unit_price
            source = f"товар каталога: ступень от {min_units} шт."
    return round(price, 2), source


async def build_offer_draft(
    *,
    need: Need,
    products: list[Product],
    passport: CapabilityPassport | None,
    capacity_units: int,
    today: date | None = None,
) -> OfferDraftResult:
    """Собрать черновик КП: значения, источники, пробелы и предупреждения."""
    today = today or date.today()
    fields: list[DraftField] = []
    missing: list[str] = []
    warnings: list[str] = []

    matching = [(product, reason) for product, reason in ((item, _matches_need(item, need)[1]) for item in products)]
    suitable = [product for product, _ in matching if _matches_need(product, need)[0]]
    for product, reason in matching:
        if reason and product not in suitable:
            warnings.append(f"Товар «{product.name}» не использован: {reason}.")

    requested_volume = int(need.volume_units)
    stock_sources: list[str] = []
    stock_total = 0
    for product in suitable:
        if product.stock_units:
            stock_total += int(product.stock_units)
            stock_sources.append(f"остаток «{product.name}»: {product.stock_units} шт.")

    business_kind = "manufacturer"
    if passport is not None:
        business_kind = str((passport.details or {}).get("business_kind") or "manufacturer")

    if business_kind == "stock_supplier":
        available = stock_total or None
        source = "; ".join(stock_sources) or "остаток склада не заполнен"
        if not available:
            missing.append("Остаток склада не заполнен: укажите наличие товара")
    elif business_kind == "both":
        candidates = [value for value in (stock_total or None, capacity_units or None) if value]
        available = min(candidates) if candidates else None
        source = "; ".join(stock_sources) or "остаток не заполнен"
        if capacity_units:
            source = f"{source}; мощность к сроку: {capacity_units} шт." if stock_sources else f"мощность к сроку: {capacity_units} шт."
        if available is None:
            missing.append("Нет ни остатка, ни подтверждённой мощности к сроку")
    else:
        available = capacity_units or None
        source = f"календарь мощностей до срока: {capacity_units} шт." if capacity_units else "мощность к сроку не заполнена"
        if not available:
            missing.append("Не заполнена доступная мощность к сроку потребности")

    if available is not None and available < requested_volume:
        warnings.append(
            f"Доступный объём {available} шт. меньше запрошенных {requested_volume} шт.: "
            "укажите реально доступный объём или откажитесь от предложения."
        )
    fields.append(
        DraftField(
            name="available_units",
            label="Доступный объём, шт.",
            value=available,
            source=source,
            confirmed=available is not None,
            note=None if available is not None else "Заполните вручную",
        )
    )

    if suitable:
        product = suitable[0]
        price, price_source = _tier_price(product, requested_volume)
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
                "Подходит несколько товаров: проверьте, что выбранный объём, покрытие и цена соответствуют заказу."
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
        missing.append("Нет товара каталога с подходящей категорией и объёмом: укажите цену вручную")

        moq = int(passport.min_order_units) if passport and passport.min_order_units else None
        moq_source = "паспорт возможностей: минимальный заказ"
        lead_time = None
        lead_source = "не задано"

    fields.append(
        DraftField(
            name="moq_units",
            label="MOQ предложения, шт.",
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
    return OfferDraftResult(
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
    return sum(
        int(entry.available_units)
        for entry in entries
        if today <= entry.date <= need.deadline_date
    )


def changed_fields(draft_payload: dict, offer_values: dict) -> list[str]:
    """Какие поля человек изменил относительно черновика."""
    changed: list[str] = []
    for name, value in offer_values.items():
        original = draft_payload.get(name)
        if original is None and value in (None, 0, 0.0):
            continue
        if isinstance(value, float) or isinstance(original, float):
            try:
                if original is not None and abs(float(original) - float(value or 0)) < 0.01:
                    continue
            except (TypeError, ValueError):
                pass
        if original != value:
            changed.append(name)
    return changed

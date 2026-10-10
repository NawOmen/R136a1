import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import notify
from .models import MarketWatch
from .category_characteristics import validate_profile_values, characteristic_profile


def classify_cargo(weight_kg: float, volume_m3: float, hazard_class: str | None = None) -> tuple[str, str]:
    """Класс задаёт маршрут оформления, но не выбирает перевозчика и не считает тариф."""
    if hazard_class:
        return "manual_review", (
            f"Опасный груз (класс {hazard_class}): класс и условия подтверждаются вручную. "
            "Площадка не классифицирует опасный груз автоматически и не называет перевозчика."
        )
    if weight_kg <= 150 and volume_m3 <= 1:
        return "small", "Мелкий опт: до 150 кг и до 1 м³. Покупатель выбирает самовывоз или перевозчика."
    if weight_kg <= 1500 and volume_m3 <= 12:
        return "medium", "Средний опт: до 1,5 т и до 12 м³. Нужны параметры грузовых мест и окно отгрузки."
    if weight_kg > 1500 or volume_m3 >= 15:
        return "large", "Большой опт: свыше 1,5 т либо от 15 м³. Требуется отдельное согласование погрузки и перевозчика."
    return "manual_review", "Объём находится в пограничном диапазоне 12–15 м³: класс и условия подтверждаются вручную."


def validate_characteristics(
    category: str, subcategory: str | None, characteristics: dict, moq_units: int
) -> tuple[list[str], list[str]]:
    errors = validate_profile_values(category, subcategory, characteristics, require_product_fields=True)
    # Preserve the existing v1 validation messages for required packaging fields.
    if category == "Упаковка и тара":
        errors = ["Для упаковки укажите материал" if error == "Укажите характеристику «Материал»" else error for error in errors]
        if subcategory == "Бумажные стаканы":
            errors = ["Для бумажных стаканов укажите объём" if error == "Укажите характеристику «Объём, мл»" else error for error in errors]
    warnings: list[str] = []
    from .category_characteristics import count_user_characteristics
    if count_user_characteristics(characteristics, category, subcategory) > 25:
        errors.append("Можно указать не более 25 пользовательских характеристик сверх системных и обязательных")
    normalized = {str(key).strip().lower(): value for key, value in characteristics.items()}
    has_profile = characteristic_profile(category, subcategory) is not None
    if category == "Упаковка и тара":
        if not has_profile and not any(key in normalized for key in ("material", "материал", "body_material")):
            errors.append("Для упаковки укажите материал")
        if subcategory == "Бумажные стаканы":
            if not has_profile and not any(key in normalized for key in ("volume_ml", "объём", "объем")):
                errors.append("Для бумажных стаканов укажите объём")
            if not any(key in normalized for key in ("coating", "покрытие", "inner_coating")):
                warnings.append("Уточните внутреннее покрытие для проверки контакта с пищевой продукцией")
    if moq_units > 1_000_000:
        warnings.append("MOQ больше 1 000 000 единиц заказа: проверьте единицу измерения")
    return errors, warnings


async def notify_market_watchers(
    db: AsyncSession, category: str, change: str, *, exclude_user_id: uuid.UUID | None = None
) -> None:
    flag = MarketWatch.demand_changes if change == "demand" else MarketWatch.supply_changes
    watches = (await db.execute(select(MarketWatch).where(MarketWatch.category == category, flag.is_(True)))).scalars().all()
    label = "спрос" if change == "demand" else "предложение"
    for watch in watches:
        if watch.user_id != exclude_user_id:
            await notify(db, watch.user_id, f"Изменилось {label} в категории «{category}»", f"market_{change}_changed")

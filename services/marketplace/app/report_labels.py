"""Russian presentation for human-readable report exports; API keys stay stable."""
LABELS = {
    "in_production":"Производство", "partially_shipped":"Частичная отгрузка", "partially_accepted":"Частичная приёмка", "disputed":"Спор",
    "created":"Оформлен", "production":"Производство", "shipped":"Отгружен", "delivered":"Доставлен",
    "partial_shipment":"Частичная отгрузка", "partial_acceptance":"Частичная приёмка", "dispute":"Спор",
    "fulfilled":"Исполнен", "cancelled":"Отменён", "returned":"Возвращён", "confirmed":"Подтверждено",
    "pending":"Ожидается", "approved":"Подтверждено", "rejected":"Отклонено", "completed":"Завершено",
    "all":"Все источники", "direct":"Прямые заказы", "group":"Групповые заказы", "manual":"Указано вручную",
    "no_vat":"Без НДС", "includes_vat":"Включая НДС", "unknown":"Неизвестно",
    "cohort_key":"Сопоставимая группа", "product_name":"Название товара", "delivery_price_rub":"Доставка, ₽",
    "discount_rub":"Скидка, ₽", "charge_lines":"Дополнительные расходы", "estimate_complete":"Полнота сметы",
    "source_refs":"Источники", "events":"События", "missing":"Недостающие сведения", "cost_revision":"Версия затрат",
    "cost_effective_from":"Затраты действуют с", "cost_source":"Источник затрат", "cost_tax_basis":"Налоговая база затрат",
    "profit_missing_reason":"Причина отсутствия прибыли", "cost_history":"История затрат", "source":"Источник",
    "kind":"Вид", "type":"Вид", "title":"Название", "amount_rub":"Сумма, ₽", "revision":"Версия",
    "unit_cost_rub":"Себестоимость единицы, ₽", "effective_from":"Действует с", "created_at":"Создано",
    "event_id":"Номер события", "deal_id":"Номер сделки", "units":"Количество", "note":"Примечание",
    "legacy_history_unknown":"Более ранняя история неизвестна", "tax_basis":"Налоговая база", "tax_rate":"Ставка налога",
    "document_id":"Номер документа", "product_id":"Номер товара", "offer_id":"Номер предложения",
    "specification_hash":"Хеш спецификации", "id":"Номер", "value":"Значение", "reason":"Причина",
}


def label(key):
    import re
    return LABELS.get(key, key if re.search('[а-яё]',str(key),re.I) else "Дополнительное поле")


def display(value):
    if value is None:
        return "Нет данных"
    if isinstance(value,bool):
        return "Да" if value else "Нет"
    if isinstance(value,dict):
        return "; ".join(f"{label(key)}: {display(item)}" for key,item in value.items())
    if isinstance(value,list):
        return "; ".join(display(item) for item in value)
    if isinstance(value,str):
        return LABELS.get(value,value)
    return str(value)

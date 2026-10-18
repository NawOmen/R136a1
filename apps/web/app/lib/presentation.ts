import { registryCharacteristicLabel } from "./categoryProfiles";

const labels: Record<string, string> = {
  certificate: "Сертификат", declaration: "Декларация соответствия", test_report: "Протокол испытаний", license: "Разрешение", other: "Прочее", specification_review: "Предметная проверка",
  draft: "Черновик", pending: "Ожидает решения", pending_review: "На проверке", active: "Действует", inactive: "Не действует",
  approved: "Подтверждено", confirmed: "Подтверждено", rejected: "Отклонено", cancelled: "Отменено", expired: "Срок истёк", completed: "Завершено",
  in_production: "Производство", disputed: "Спор",
  created: "Оформлен", accepted: "Принят", ordered: "Оформлен", production: "Производство", shipped: "Отгружен", delivered: "Доставлен", fulfilled: "Исполнен", returned: "Возвращён",
  partially_shipped: "Частично отгружен", partially_accepted: "Частично принят", awaiting_approval: "Ожидает подтверждения", collecting: "Набор участников", ready: "Готов", failed: "Ошибка", success: "Успешно", queued: "В очереди", running: "Выполняется", needs_input: "Требуется уточнение",
  open: "Открыто", in_progress: "В работе", resolved: "Решено", closed: "Закрыто", verified: "Проверено", unverified: "Не проверено", assumed: "Предполагается", needs_clarification: "Нужно уточнить", confirmed_by_user: "Подтверждено пользователем", ready_for_review: "Готово к проверке",
  all: "Все источники", direct: "Прямой заказ", group: "Групповой заказ", manual: "Указано вручную", agent: "Из материалов", manual_override: "Исправлено пользователем", calculated: "Рассчитано системой", unknown: "Неизвестно",
  local: "Локальная обработка", local_qwen: "Локальная модель", external: "Внешняя проверка", rules_only: "Программные правила", model: "Модель", human: "Человек", calculator: "Расчётный модуль", system: "Система", cold: "Холодный", warm: "Тёплый", hot: "Горячий",
  n1: "Отказ одного поставщика", n2: "Отказ двух поставщиков", included: "Включено", excluded: "Не включено", not_applicable: "Не применяется",
  buyer_agent: "Агент покупателя", seller_agent: "Агент продавца", marketplace: "Маркетплейс", coalition: "Объединённая партия", resilience: "Устойчивость поставки",
  company: "Компания", product: "Товар", need: "Потребность", deal: "Сделка", order: "Заказ", document: "Документ", resource_reservation: "Резерв ресурса", agent_run: "Анализ ИИ", approval: "Подтверждение", reserve: "Резерв",
  extract_requirements: "Извлечение требований", extract_text: "Чтение текста", extract_document: "Чтение документа", extract_image: "Распознавание изображения", extract_audio: "Распознавание речи", extract_material: "Чтение материала", search_capability_passports: "Подбор производителей", review_anonymized_facts: "Проверка полноты источников", invalidate_source: "Исключение источника", confirm_requirements: "Подтверждение требований", clarify_requirements: "Уточнение требований", external_route_fallback: "Возврат к локальной обработке",
  capability_passport_saved: "Сохранён паспорт возможностей", document_uploaded: "Загружен документ", document_verified: "Документ проверен", document_rejected: "Документ отклонён", document_deleted: "Документ удалён", product_specification_checked: "Проверена спецификация товара", capability_scope_checked: "Проверена область возможностей", resource_consumed: "Учтено использование ресурса", human_approval_recorded: "Сохранено подтверждение человека",
  rate_limit_exceeded: "Превышен лимит запросов", rate_limit_alert: "Предупреждение о частоте запросов", login_failed: "Неудачный вход", login_success: "Успешный вход", access_denied: "Доступ запрещён",
  category: "Категория", subcategory: "Подкатегория", characteristics: "Характеристики", quantity_units: "Количество", volume_units: "Количество", budget_rub: "Бюджет, ₽", lead_time_days: "Срок, дней", delivery_city: "Город доставки", deadline_date: "Срок поставки", valid_until: "Срок действия", delivery_address_id: "Адрес доставки", evidence: "Подтверждение требований",
  category_id: "Категория", source: "Источник", source_id: "Источник", source_name: "Название источника", source_kind: "Вид источника", content_hash: "Хеш содержимого", sources: "Источники", source_refs: "Ссылки на источники", locator: "Положение в источнике", excerpt: "Фрагмент источника", confidence: "Уверенность", label: "Название", key: "Поле", value: "Значение", status: "Статус", properties: "Требования", conflicts: "Противоречия", questions: "Вопросы", warnings: "Предупреждения", matches: "Кандидаты", summary: "Результат", can_confirm: "Можно подтвердить", buyer_company_id: "Компания покупателя", original_value: "Исходное значение", original_unit: "Исходная единица", normalized_unit: "Единица хранения", confirmed_by_user_id: "Кем подтверждено", confirmed_at: "Когда подтверждено", resolved_conflicts: "Разрешённые противоречия",
  unit: "Единица заказа", dimensions_mm: "Габариты, мм", print: "Печать", top_diameter_mm: "Диаметр верха, мм", bottom_diameter_mm: "Диаметр дна, мм", width_mm: "Ширина, мм", length_mm: "Длина, мм", body_material: "Материал", inner_coating: "Покрытие", product_type: "Тип изделия", material_grade: "Марка материала", complexity: "Сложность и операции", packaging: "Упаковка", quality_control: "Контроль качества", trial_batch: "Пробная партия", mandatory_requirements: "Обязательные требования",
  cohort_key: "Сопоставимая группа", product_name: "Название товара", delivery_price_rub: "Доставка, ₽", discount_rub: "Скидка, ₽", charge_lines: "Дополнительные расходы", estimate_complete: "Полнота сметы", events: "События", missing: "Недостающие сведения", cost_revision: "Версия затрат", cost_effective_from: "Затраты действуют с", cost_source: "Источник затрат", cost_tax_basis: "Налоговая база затрат", profit_missing_reason: "Причина отсутствия прибыли", cost_history: "История затрат", type: "Вид", amount_rub: "Сумма, ₽", date: "Дата", name: "Название", id: "Номер", notes: "Примечания",
  unchanged: "Без изменений", new: "Новый", updated: "Обновлён", added: "Добавлен", skipped: "Пропущен", changed: "Изменён", created_at: "Создано", unit_price_rub: "Цена за единицу, ₽", moq_units: "Минимальный заказ", stock_units: "Остаток", is_published: "Опубликован", price_tiers: "Ценовые ступени", min_units: "Минимальное количество", delivery_region: "Регион доставки", request_text: "Описание покупателя", text: "Текст", image: "Изображение", audio: "Аудиозапись",
};

export function russianLabel(key: string, fallback = "Дополнительное поле"): string {
  return labels[key] ?? registryCharacteristicLabel(key) ?? (/[а-яё]/i.test(key) ? key : fallback);
}

/** Data such as names, model versions, materials and original excerpts are not translated. */
export function displayValue(value: unknown): string {
  if (value == null || value === "") return "Не указано";
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  if (Array.isArray(value)) return value.map(displayValue).join("; ");
  if (typeof value === "object") return Object.entries(value).map(([key, item], index) => `${russianLabel(key, `Дополнительное поле № ${index + 1}`)}: ${displayValue(item)}`).join("; ");
  if (typeof value === "string") return labels[value] ?? value;
  return String(value);
}

/** System explanations may contain enum names; original excerpts do not use this helper. */
export function systemText(value: string): string {
  return value.replace(/[a-z][a-z0-9_.-]*/gi, token => labels[token] ?? token);
}

export function fieldName(key: string): string {
  // Unknown names may be the user's own terminology; do not alter their data.
  return key ? labels[key] ?? registryCharacteristicLabel(key) ?? key : "";
}

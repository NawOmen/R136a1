# Сценарный анализ этапа 16

Внутренние расчётные сценарии команды; числа — явно заданные допущения.

Денежные результаты в рублях. null означает неизвестное или несопоставимое.

| Сценарий | Исход | Покупатель: стоимость / время, ₽ | Поставщик: вклад / время, ₽ | Платформа: результат, ₽ | Резерв: ожидаемый эффект, ₽ |
|---|---|---|---|---|---|
| direct: Прямой запрос с сопоставимой альтернативой | completed | 600.00 | 200.00 | -97.00 | не определено |
| corrections: Правки и повторы съедают выигрыш | completed | -700.00 | -500.00 | -97.00 | не определено |
| below-moq: Группа не набрана: переход к прямому запросу | blocked | не определено | не определено | -97.00 | не определено |
| expensive-reserve: Резерв слишком дорог при заданной чувствительности | completed | 600.00 | 200.00 | -97.00 | -2620.00 |
| unknown: Неизвестные цена альтернативы, затраты и платежи | completed | не определено | не определено | не определено | не определено |
| repeat: Повтор существующего клиента: дополнительный объём нулевой | completed | 700.00 | 300.00 | -97.00 | не определено |
| additional-volume: Заданный дополнительный объём и сценарная подписка | completed | 450.00 | 900.00 | 53.00 | не определено |
| incomparable: Другие количество и налоговая база | completed | не определено | не определено | -97.00 | не определено |
| abandoned: Незавершённый запрос с затратами на повтор | abandoned | не определено | не определено | -97.00 | не определено |
| unknown-time: Неизвестные трудозатраты и стоимость переключения | completed | не определено | 200.00 | -97.00 | не определено |
| known-supplier: Постоянный поставщик: лишняя автоматизация дороже | completed | -250.00 | -350.00 | -97.00 | не определено |
| commission: Сценарная комиссия поставщика включена в его расходы | completed | 600.00 | 750.00 | 53.00 | не определено |

## Все листья текущего каталога

Профили и предметные примеры анализируются для каждого листа. Число товаров и прохождение коммерческого пути — отдельные свойства.

| ID / раздел / лист | Допуск | Обязательные поля | Единицы | Проверки приёмки | Рабочее наполнение |
|---|---|---|---|---|---|
| packaging.paper-cups / Упаковка и тара / Бумажные стаканы | existing_rules | material, volume_ml | шт, упак | объём, швы, герметичность | профиль |
| packaging.food-packaging / Упаковка и тара / Пищевая упаковка | existing_rules | material, dimensions_mm, purpose | шт, упак | размер, материал, чистота | профиль |
| packaging.bags / Упаковка и тара / Пакеты | existing_rules | material, dimensions_mm, thickness_mm | шт, упак | размер, толщина, швы | есть |
| packaging.boxes / Упаковка и тара / Коробки | existing_rules | material, dimensions_mm | шт, упак | размер, прочность, комплектность | есть |
| packaging.bottles-canisters / Упаковка и тара / Бутылки и канистры | existing_rules | material, volume_ml, purpose | шт, упак | объём, крышка, герметичность | профиль |
| packaging.film / Упаковка и тара / Плёнка | existing_rules | material, width_mm, thickness_mm | м, кг, рулон, г, мм | ширина, толщина, длина рулона | есть |
| materials.paper-cardboard / Сырьё и материалы / Бумага и картон | existing_rules | material, format, grammage_g_m2 | кг, м², шт, упак, г, см² | формат, плотность, влажность | профиль |
| materials.polymers / Сырьё и материалы / Полимеры | existing_rules | material, grade | кг, т, г | марка, партия, паспорт качества | профиль |
| materials.metals / Сырьё и материалы / Металлы | existing_rules | material, grade, dimensions_mm, standard | кг, т, м, шт, г, мм | марка, размер, партия, сертификат качества | профиль |
| materials.textile / Сырьё и материалы / Текстиль | existing_rules | composition, width_cm | м, м², рулон, шт, мм, см² | состав, ширина, плотность, дефекты | есть |
| materials.chemical-feedstock / Сырьё и материалы / Химическое сырьё | existing_rules | composition, grade, purpose, storage_conditions | кг, т, л, г, мл | состав, партия, паспорт безопасности | профиль |
| equipment.manufacturing / Оборудование / Производственное | existing_rules | model, process, power_kw | шт, комплект | модель, паспорт, проверка запуска | профиль |
| equipment.retail / Оборудование / Торговое | existing_rules | model, dimensions_mm, purpose | шт, комплект | модель, размеры, комплектность | профиль |
| equipment.warehouse / Оборудование / Складское | existing_rules | model, dimensions_mm, weight_kg | шт, комплект | модель, грузоподъёмность, комплектность | профиль |
| equipment.food / Оборудование / Пищевое | existing_rules | model, process, power_kw | шт, комплект | модель, материалы контакта, запуск | профиль |
| equipment.spare-parts / Оборудование / Запасные части | existing_rules | model, compatibility, material | шт, комплект | номер детали, совместимость, размеры | профиль |
| construction.finishing / Строительство / Отделочные материалы | existing_rules | material, purpose, product_kind | шт, м, м², кг, упак, мешок, м³, г, мм, см², мл | размер, покрытие, партия, дефекты | есть |
| construction.fasteners / Строительство / Крепёж | existing_rules | material, standard, product_kind | шт, кг, упак, г | резьба, диаметр, длина, класс | есть |
| construction.engineering / Строительство / Инженерные системы | existing_rules | model, dimensions_mm, purpose | шт, м, комплект, мм | модель, присоединение, назначение | профиль |
| construction.tools / Строительство / Инструмент | existing_rules | model, material, purpose | шт, комплект | модель, назначение, комплектность | профиль |
| food.drinks / Продукты питания / Напитки | existing_rules | composition, volume_ml, storage_conditions, shelf_life_days | шт, л, упак, мл | партия, маркировка, срок, упаковка | профиль |
| food.groceries / Продукты питания / Бакалея | existing_rules | composition, grade, storage_conditions, shelf_life_days | кг, т, шт, упак, г | партия, масса, срок, маркировка | профиль |
| food.frozen / Продукты питания / Замороженная продукция | existing_rules | composition, storage_conditions, temperature_min_c, temperature_max_c, shelf_life_days | кг, шт, упак, г | температурная цепь, партия, срок | профиль |
| food.ingredients / Продукты питания / Ингредиенты | existing_rules | composition, grade, purpose, storage_conditions, shelf_life_days | кг, т, л, г, мл | состав, партия, срок, назначение | профиль |
| business-supplies.stationery / Товары для бизнеса / Канцелярия | existing_rules | material, format | шт, упак, комплект | формат, количество, комплектность | профиль |
| business-supplies.household / Товары для бизнеса / Хозяйственные товары | existing_rules | material, purpose, dimensions_mm | шт, упак, комплект | материал, назначение, размеры | профиль |
| business-supplies.workwear / Товары для бизнеса / Спецодежда | existing_rules | composition, size, purpose | шт, комплект | размер, состав, защитное назначение | есть |
| business-supplies.furniture / Товары для бизнеса / Мебель | existing_rules | material, dimensions_mm, finish | шт, комплект | размер, покрытие, сборка, устойчивость | есть |
| electronics.components / Электроника / Компоненты | existing_rules | model, product_kind | шт, упак, м, бухта, мм | модель, напряжение, интерфейс | есть |
| electronics.computers / Электроника / Компьютерная техника | existing_rules | model, interface | шт, комплект | модель, конфигурация, комплектность | профиль |
| electronics.communication / Электроника / Связь | existing_rules | model, interface, purpose | шт, комплект | модель, интерфейс, работоспособность | профиль |
| electronics.automation / Электроника / Автоматизация | existing_rules | model, voltage_v, interface, process | шт, комплект | модель, напряжение, интерфейс, процесс | профиль |
| transport.containers / Транспорт и логистика / Тара для перевозки | existing_rules | material, dimensions_mm, weight_kg | шт, комплект | размер, грузоподъёмность, комплектность | профиль |
| transport.components / Транспорт и логистика / Комплектующие | existing_rules | model, compatibility, material | шт, комплект | модель, совместимость, материал | профиль |
| transport.warehousing / Транспорт и логистика / Складские услуги | existing_rules | service_scope, storage_conditions, output | шт, м², комплект, см² | объём услуги, условия, акт | профиль |
| printing.labels / Полиграфия и реклама / Этикетки | existing_rules | material, dimensions_mm, finish | шт, рулон, м², см² | размер, материал, адгезия, печать | профиль |
| printing.printing / Полиграфия и реклама / Печать | existing_rules | material, format, process, color | шт, м², комплект, см² | формат, цвет, согласованный макет | профиль |
| printing.signs / Полиграфия и реклама / Вывески | existing_rules | material, dimensions_mm, process | шт, комплект | размер, материал, крепление, макет | профиль |
| printing.merchandise / Полиграфия и реклама / Сувенирная продукция | existing_rules | material, dimensions_mm, process | шт, комплект | размер, материал, согласованный макет | профиль |
| manufacturing-services.contract-manufacturing / Услуги производства / Контрактное производство | existing_rules | process, material, output | шт, кг, м, комплект, г, мм | спецификация, результат, акт | профиль |
| manufacturing-services.packing / Услуги производства / Фасовка | existing_rules | process, packaging, output | шт, кг, упак, г | масса, тара, маркировка, акт | профиль |
| manufacturing-services.processing / Услуги производства / Обработка | existing_rules | process, material, dimensions_mm, standard | шт, кг, м, м², г, мм, см² | размер, допуск, стандарт, акт | профиль |
| manufacturing-services.assembly / Услуги производства / Сборка | existing_rules | process, compatibility, output | шт, комплект | совместимость, комплектность, акт | профиль |
| medical-hygiene.consumables / Медицина и гигиена / Расходные материалы | unsupported | material, size, purpose | шт, упак | назначение, регистрация, партия | профиль |
| medical-hygiene.protection / Медицина и гигиена / Средства защиты | existing_rules | material, size, purpose | шт, комплект, упак | защитное назначение, размер, маркировка | профиль |
| medical-hygiene.hygiene / Медицина и гигиена / Гигиеническая продукция | existing_rules | composition, purpose, packaging | шт, л, упак, мл | состав, назначение, партия | профиль |
| other.other-products / Другое / Другая продукция | existing_rules | purpose, material, dimensions_mm | шт, кг, м, м², л, рулон, упак, комплект, г, мм, см², мл | согласованная спецификация и назначение | профиль |

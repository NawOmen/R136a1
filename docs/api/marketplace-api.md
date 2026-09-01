# API-контракт — Marketplace Service (v1)

Версия: 1.0 · Сервис: `marketplace` · Базовый префикс: `/api/v1`

Сервис хранит бизнес-данные маркетплейса: адреса доставки, производственные профили, товары, мощности, документы, Capability Passport, потребности, предложения, сделки и уведомления. Схема БД — `marketplace`; юридические компании и членство находятся в `gateway-auth` (схема `auth`), на них стоят кросс-схемные ссылки по `company_id`.

## Маршруты этапа 5

- `POST /market/rematch` — записать событие и повторить подбор.
- `GET /companies/{company_id}/market-opportunities` — персональная лента производителя.
- `POST /opportunities/{id}/prepare-offer` — создать непубличный черновик без цены.
- `POST /group-offers/{id}/publish` — проверить и вручную подтвердить групповые условия.
- `GET /coalitions/mine` — коалиции покупателя/производителя с приватными условиями.
- `POST /coalitions/{id}/decision` — отдельное согласие или отказ покупателя.
- `POST /needs/{id}/optimize` — варианты «Дешевле», «Сбалансированный», «Надёжнее».
- `PATCH /offers/{id}` — изменение цены, MOQ, срока или мощности с повторным подбором.

Обычное предложение хранит производственную цену и стоимость логистики отдельно;
бюджет и итог сделки проверяются по их сумме.

Публикация группового предложения и решение покупателя — Human Approval actions.
Ни один из этих маршрутов не использует LLM для денежных расчётов.

Аутентификация — JWT Bearer (тот же секрет, что у gateway-auth). В токене `sub` = `user_id`. Каждое действие выполняется от имени `company_id` (передаётся в пути или теле), а пользователь фиксируется как `performed_by_user_id` (= `created_by_user_id`).

## Разрешения (проверяются по схеме `auth`)

- `require_verified_company` — компания в статусе `verified`;
- `require_company_buyer` — членство с `can_buy = true`;
- `require_company_seller` — членство с `can_sell = true`;
- `require_company_admin` — членство с `is_admin = true`.

## Объекты

### DeliveryAddress

```json
{ "id": "uuid", "company_id": "uuid", "address": "...", "city": "...", "region": "...", "is_default": false }
```

### ProductionProfile

```json
{
  "company_id": "uuid",
  "production_site_address": "...",
  "region": "Свердловская область",
  "about": "..."
}
```

### Product

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "name": "Стакан 400 мл PE",
  "category": "бумажные стаканы",
  "characteristics": { "volume_ml": 400, "coating": "PE", "material": "крафт-картон 300 г/м²" },
  "price_rub": 11.2,
  "moq_units": 20000,
  "lead_time_days": 9,
  "is_published": true
}
```

`characteristics` — JSONB (гибкие характеристики); `category` и `characteristics->>'volume_ml'` индексируются для фильтрации.

### CapacityEntry

```json
{ "date": "2026-10-21", "available_units": 4800 }
```

### Document

```json
{ "id": "uuid", "company_id": "uuid", "name": "Декларация ТР ТС 005/2011", "document_type": "certificate", "file_key": "companies/<id>/<uuid>.pdf", "content_type": "application/pdf" }
```

### CapabilityPassport

```json
{
  "company_id": "uuid",
  "technologies": ["высечка бумажных стаканов"],
  "equipment": ["высекальный пресс"],
  "materials": ["крафт-картон 260–320 г/м²"],
  "size_ranges": { "cup_volume_ml": [150, 600] },
  "tolerances": "±0,5 мм",
  "certifications": ["ТР ТС 005/2011"],
  "min_order_units": 20000,
  "max_order_units": 48000,
  "delivery_regions": ["Центральный ФО"],
  "completed_order_types": ["стаканы 300–450 мл"]
}
```

Массивы и объекты — JSONB.

### Need

```json
{
  "id": "uuid",
  "company_id": "uuid",
  "created_by_user_id": "uuid",
  "category": "бумажные стаканы",
  "characteristics": { "volume_ml": 400, "coating": "PE" },
  "volume_units": 120000,
  "budget_rub": 1900000,
  "deadline_date": "2026-10-30",
  "delivery_address_id": "uuid",
  "visibility": "open_anonymized",
  "status": "open_for_offers",
  "files": [ { "id": "uuid", "file_name": "tz.pdf", "content_type": "application/pdf" } ]
}
```

- `visibility`: `open_anonymized` | `selected_producers` | `closed`.
- `status`: `draft` | `open_for_offers` | `matched` | `cancelled` | `expired`.

Открытая лента возвращает обезличенную форму карточки без `company_id`,
`created_by_user_id`, бюджета, адреса доставки и исходных файлов.

### Offer

```json
{
  "id": "uuid",
  "need_id": "uuid",
  "company_id": "uuid",
  "created_by_user_id": "uuid",
  "price_rub": 11.2,
  "available_units": 48000,
  "lead_time_days": 9,
  "status": "sent"
}
```

`status`: `sent` | `selected` | `rejected`.

### Deal

```json
{
  "id": "uuid",
  "offer_id": "uuid",
  "need_id": "uuid",
  "buyer_company_id": "uuid",
  "seller_company_id": "uuid",
  "performed_by_user_id": "uuid",
  "units": 48000,
  "total_price_rub": 537600.0,
  "status": "created"
}
```

`status`: `created`.

### Notification

```json
{ "id": "uuid", "user_id": "uuid", "message": "...", "type": "offer_received", "is_read": false }
```

## Эндпоинты

Все эндпоинты требуют Bearer, кроме публичного каталога и health.

### Адреса доставки (режим «Покупаю»)

- `GET /companies/{company_id}/addresses` — список (buyer).
- `POST /companies/{company_id}/addresses` — body `{address, city, region, is_default}` (buyer + admin компании). `201`.
- `PATCH /companies/{company_id}/addresses/{address_id}` — обновить (buyer + admin).
- `DELETE /companies/{company_id}/addresses/{address_id}` — удалить (buyer + admin).

### Производственный профиль (режим «Продаю»)

- `GET /companies/{company_id}/production-profile` — получить (seller).
- `PUT /companies/{company_id}/production-profile` — upsert body `{production_site_address, region, about}` (seller + admin).

### Товары

- `GET /products` — публичный каталог (только `is_published=true`). Без Bearer.
- `GET /companies/{company_id}/products` — товары компании, включая неопубликованные (seller).
- `POST /companies/{company_id}/products` — создать (seller + admin). `201`.
- `PATCH /products/{product_id}` — обновить (seller + admin своей компании).
- `POST /products/{product_id}/publish` — body `{published: bool}` (seller + admin;
  для публикации также требуется статус компании `verified`).

### Мощности

- `GET /companies/{company_id}/capacity?from=...&to=...` — записи календаря (seller).
- `PUT /companies/{company_id}/capacity` — body `{entries: [{date, available_units}]}` — перезаписать (seller + admin).

### Документы

- `GET /companies/{company_id}/documents` — список (seller).
- `POST /companies/{company_id}/documents` — multipart: `file` + поля `name`, `document_type` (seller + admin). `201`.
- `DELETE /documents/{document_id}` — удалить (seller + admin своей компании).

### Capability Passport

- `GET /companies/{company_id}/capability-passport` — получить (seller).
- `PUT /companies/{company_id}/capability-passport` — upsert (seller + admin).

### Потребности (режим «Покупаю»)

- `GET /needs/mine` — мои потребности; `GET /needs?seller_company_id=...` — обезличенная лента открытых запросов подходящей товарной категории для компании-продавца.
- `POST /needs` — создать черновик body `{company_id, category, characteristics, volume_units, budget_rub, deadline_date, delivery_address_id, visibility}` (buyer + admin компании). `201`.
- `POST /needs/{need_id}/publish` — опубликовать черновик (buyer + admin + проверенная компания).
- `GET /needs/{need_id}` — деталь (участники: покупатель или продавец).
- `POST /needs/{need_id}/files` — multipart `file` (buyer + admin своей потребности, только в статусе `draft`).
- `GET /need-files/{file_id}/download` — скачать исходный файл (только buyer своей потребности).
- `POST /needs/{need_id}/cancel` — отменить (buyer своей потребности).

### Предложения (режим «Продаю»)

- `GET /needs/{need_id}/offers` — предложения по потребности (покупатель видит все, продавец — только свои).
- `POST /needs/{need_id}/offers` — body `{company_id, price_rub, available_units, lead_time_days}` (seller, проверенная компания; одно предложение от компании; нельзя отвечать своей компании). `201`.

### Сделка (выбор предложения покупателем)

- `POST /offers/{offer_id}/select` — покупатель выбирает предложение → создаёт сделку, потребность → `matched`, выбранное предложение → `selected`, остальные → `rejected`. `201` → Deal.

### Устойчивость сделки (этап 6)

- `POST /needs/{need_id}/resilience-plans` — покупатель создаёт план из выполнимого варианта оптимизатора и задаёт пороги цены/срока.
- `GET /resilience-plans/mine` и `GET /resilience-plans/{id}` — планы покупателя с основной конфигурацией, резервами, N-1/N-2 и аудитом.
- `POST /resilience-plans/{id}/confirm` — Human Approval покупателя до активации плана.
- `POST /resilience-plans/{id}/simulate-failure` — безопасный N-1/N-2 расчёт без изменения действующей конфигурации.
- `GET /reserve-invitations/{company_id}` — только собственные приглашения производителя; чужие коммерческие условия не раскрываются.
- `POST /reserve-commitments/{id}/decision` — производитель подтверждает цену, мощность, MOQ, срок и дату удержания либо отклоняет резерв.
- `GET /primary-obligations/{company_id}` — собственные подтверждённые основные назначения производителя.
- `POST /resilience-plans/{id}/failures` — основной производитель сообщает о фактическом сбое; блокируется только его объём, резервы требуют повторного подтверждения.
- `POST /resilience-scenarios/{id}/approve` — покупатель подтверждает полную замену, если она не была заранее разрешена порогами.

Холодный и неподтверждённый тёплый резерв не считаются гарантированным покрытием.
LLM не вызывает активацию резерва и не меняет цену или статус плана.

### Уведомления

- `GET /notifications` — мои уведомления.
- `POST /notifications/{notification_id}/read` — отметить прочитанным.
- `POST /notifications/read-all` — отметить все.

### Health

- `GET /health` → `{"status": "ok"}`.

## Ошибки

Единый формат: `{"detail": "текст"}`. Коды: `401` — нет/неверный токен; `403` — нет прав/компания не проверена; `404` — не найдено; `409` — конфликт; `422` — ошибка валидации.

## Файлы

Файлы хранятся в MinIO. При загрузке через multipart сервис сохраняет объект в MinIO (ключ `file_key` в БД). Допустимые типы: изображения, PDF, аудио и безопасный простой текст (`text/plain`, `text/markdown`). Пустые файлы отклоняются, размер — до 25 МБ. Исходные файлы потребности не попадают в открытую ленту и скачиваются только участником компании-покупателя.

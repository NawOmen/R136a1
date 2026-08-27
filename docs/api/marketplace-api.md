# API-контракт — Marketplace Service (v1)

Версия: 1.0 · Сервис: `marketplace` · Базовый префикс: `/api/v1`

Сервис хранит бизнес-данные маркетплейса: адреса доставки, производственные профили, товары, мощности, документы, Capability Passport, потребности, предложения, сделки и уведомления. Схема БД — `marketplace`; юридические компании и членство находятся в `gateway-auth` (схема `auth`), на них стоят кросс-схемные ссылки по `company_id`.

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
- `status`: `open_for_offers` | `matched` | `cancelled` | `expired`.

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
- `POST /products/{product_id}/publish` — body `{published: bool}` (seller + admin).

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

- `GET /needs?mine=true` — мои потребности (buyer); `GET /needs` — открытая лента (для продавца, `open_anonymized`).
- `POST /needs` — body `{company_id, category, characteristics, volume_units, budget_rub, deadline_date, delivery_address_id, visibility}` (buyer, проверенная компания). `201`.
- `GET /needs/{need_id}` — деталь (участники: покупатель или продавец).
- `POST /needs/{need_id}/files` — multipart `file` (buyer своей потребности).
- `POST /needs/{need_id}/cancel` — отменить (buyer своей потребности).

### Предложения (режим «Продаю»)

- `GET /needs/{need_id}/offers` — предложения по потребности (покупатель видит все, продавец — только свои).
- `POST /needs/{need_id}/offers` — body `{company_id, price_rub, available_units, lead_time_days}` (seller, проверенная компания). `201`.

### Сделка (выбор предложения покупателем)

- `POST /offers/{offer_id}/select` — покупатель выбирает предложение → создаёт сделку, потребность → `matched`, выбранное предложение → `selected`, остальные → `rejected`. `201` → Deal.

### Уведомления

- `GET /notifications` — мои уведомления.
- `POST /notifications/{notification_id}/read` — отметить прочитанным.
- `POST /notifications/read-all` — отметить все.

### Health

- `GET /health` → `{"status": "ok"}`.

## Ошибки

Единый формат: `{"detail": "текст"}`. Коды: `401` — нет/неверный токен; `403` — нет прав/компания не проверена; `404` — не найдено; `409` — конфликт; `422` — ошибка валидации.

## Файлы

Файлы хранятся в MinIO. При загрузке через multipart сервис сохраняет объект в MinIO (ключ `file_key` в БД). Допустимые типы: изображения, PDF, аудио. Размер — до 25 МБ.

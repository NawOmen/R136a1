# API-контракт — Gateway Auth (v1)

Версия контракта: 1.0 · Сервис: `gateway-auth` · Базовый префикс: `/api/v1`

Сервис `gateway-auth` отвечает за аккаунты, вход, компании, членство и демонстрационную проверку. Все ответы в формате JSON. Аутентификация — JWT Bearer: заголовок `Authorization: Bearer <token>`.

ФИО хранится в трёх колонках: `last_name` (фамилия), `first_name` (имя), `middle_name` (отчество, необязательное). Единого поля `full_name` нет.

## Объекты

### User

```json
{
  "id": "uuid",
  "last_name": "Иванов",
  "first_name": "Иван",
  "middle_name": "Иванович",
  "email": "ivan@demo.ru",
  "phone": "+7 900 000-00-00",
  "account_status": "active",
  "is_marketplace_admin": false
}
```

- `middle_name` и `phone` могут быть `null`.
- `account_status`: `active` | `blocked`.
- `is_marketplace_admin`: глобальное разрешение администратора прототипа (не выбирается при регистрации).

### Company

```json
{
  "id": "uuid",
  "full_name": "Общество с ограниченной ответственностью «Ромашка»",
  "display_name": "ООО «Ромашка»",
  "legal_form": "ООО",
  "inn": "1234567890",
  "ogrn": "1234567890123",
  "ogrnip": null,
  "kpp": "123456789",
  "legal_address": "г. Москва, ул. Примерная, д. 1",
  "country": "RU",
  "verification_status": "draft"
}
```

- `legal_form`: `ООО` | `ИП`.
- `ogrn`, `ogrnip`, `kpp` могут быть `null` (для ИП — `ogrnip`, для ООО — `ogrn`).
- `verification_status`: `draft` | `pending_review` | `verified` | `rejected`.

### Membership (членство пользователя в компании)

Вкладывается в объекты компании при запросе от имени текущего пользователя:

```json
{
  "can_buy": true,
  "can_sell": true,
  "is_admin": true
}
```

## Эндпоинты

### `GET /health`

Без авторизации. Ответ: `{"status": "ok"}`.

### `POST /api/v1/auth/register`

Создаёт аккаунт (статус `active`, пароль хешируется) и возвращает JWT.

Запрос:

```json
{
  "last_name": "Иванов",
  "first_name": "Иван",
  "middle_name": "Иванович",
  "email": "ivan@demo.ru",
  "password": "secret123",
  "phone": "+7 900 000-00-00"
}
```

`middle_name` и `phone` необязательны. Ответ `201`:

```json
{
  "user": { "...": "см. User" },
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

Ошибка `409`, если email уже занят.

### `POST /api/v1/auth/login`

Запрос: `{"email": "...", "password": "..."}`. Ответ `200` — как у регистрации. `401` при неверных данных или заблокированном аккаунте.

### `GET /api/v1/auth/me`

Требует Bearer. Ответ `200`:

```json
{
  "user": { "...": "см. User" },
  "companies": [
    {
      "id": "uuid",
      "full_name": "...",
      "display_name": "...",
      "legal_form": "ООО",
      "inn": "...",
      "ogrn": "...",
      "ogrnip": null,
      "kpp": "...",
      "legal_address": "...",
      "country": "RU",
      "verification_status": "draft",
      "membership": { "can_buy": true, "can_sell": true, "is_admin": true }
    }
  ]
}
```

### `POST /api/v1/companies`

Требует Bearer. Создаёт компанию со статусом `draft` и членство текущего пользователя (`is_admin: true`).

Запрос:

```json
{
  "full_name": "Общество с ограниченной ответственностью «Ромашка»",
  "display_name": "ООО «Ромашка»",
  "legal_form": "ООО",
  "inn": "1234567890",
  "ogrn": "1234567890123",
  "ogrnip": null,
  "kpp": "123456789",
  "legal_address": "г. Москва, ул. Примерная, д. 1",
  "can_buy": true,
  "can_sell": true
}
```

Ответ `201` — объект компании (см. Company) с полем `membership`.

### `PATCH /api/v1/companies/{company_id}`

Требует Bearer и права администратора компании. Обновляет поля профиля (допустимо в статусах `draft` и `rejected`). Ответ `200` — обновлённая компания.

### `POST /api/v1/companies/{company_id}/submit-review`

Требует Bearer и права администратора компании. Переводит компанию в `pending_review` (из `draft` или `rejected`). Ответ `200` — компания.

### `GET /api/v1/admin/companies?status=pending_review`

Требует Bearer и `is_marketplace_admin = true`. Ответ `200`:

```json
{ "companies": [ { "...": "см. Company" } ] }
```

### `POST /api/v1/admin/companies/{company_id}/verification`

Требует Bearer и `is_marketplace_admin = true`. Записывает решение в журнал проверок.

Запрос:

```json
{ "decision": "approve", "reason": "реквизиты корректны" }
```

`decision`: `approve` | `reject`. Ответ `200` — компания со статусом `verified` или `rejected`.

### `POST /api/v1/admin/users/{user_id}/block`

Требует Bearer и `is_marketplace_admin = true`. Запрос: `{"blocked": true}`. Ответ `200` — пользователь со статусом `active`/`blocked`.

## Ошибки

Единый формат ошибки: `{"detail": "текст ошибки"}`. Коды: `401` — нет/неверный токен; `403` — недостаточно прав; `404` — не найдено; `409` — конфликт (например, занятый email).

## Версионирование

Контракт хранится под префиксом `/api/v1`. При несовместимых изменениях добавляется `/api/v2` без удаления старого префикса.

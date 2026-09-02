# API этапа 7 — `/api/v1`

Все методы требуют Bearer JWT.

- `POST /support/tickets`, `GET /support/tickets/mine` — создать и читать свои обращения.
- `GET /admin/support/tickets`, `PATCH /admin/support/tickets/{id}` — очередь и решение поддержки; только администратор площадки.
- `GET /audit/events` — доступные пользователю события своей компании; администратор может фильтровать площадку.
- `GET /audit/verify` — проверка полной хеш-цепочки; только администратор площадки.
- `GET /kpi?company_id=...` — показатели компании из журнала; без `company_id` администратор получает показатели площадки.
- `GET /admin/companies?status=...&search=...` — фильтры очереди компаний.
- `GET /admin/companies/{id}/verification-events` — история решений по компании.

`AgentRunOut` дополнен совместимыми nullable-полями: `duration_ms`, `input_chars`, `output_chars`, `estimated_cost_rub`, `cost_basis`.

"use client";

// Мои потребности (GET /needs?mine=true): статус, объём, бюджет, срок,
// переход к деталям.

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import {
  ApiError,
  formatRub,
  formatUnits,
  marketplace,
  Need,
  NEED_STATUS_LABELS,
} from "../lib/marketplace";
import { useMe } from "../lib/useMe";

export default function MyNeedsPage() {
  useMe(); // проверка входа и данных аккаунта
  const [needs, setNeeds] = useState<Need[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    marketplace
      .getMyNeeds(token)
      .then(setNeeds)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Не удалось загрузить потребности."),
      )
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="hint">Загрузка...</p>;

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Мои потребности</h1>
        <Link href="/needs/new" className="btn btn-primary btn-sm">
          Создать потребность
        </Link>
      </div>
      <p className="subtitle">Потребности, созданные вашими компаниями</p>

      {error && <div className="alert alert-error">{error}</div>}

      {!error && needs.length === 0 ? (
        <p className="hint">
          Потребностей пока нет. Создайте первую — производители смогут предложить свои условия.
        </p>
      ) : (
        <ul className="company-list">
          {needs.map((need) => (
            <li key={need.id}>
              <Link href={`/needs/${need.id}`} className="company-item">
                <span className="company-item__name">
                  {need.category} · {formatUnits(need.volume_units)}
                </span>
                <span className="company-meta">
                  Бюджет: {formatRub(need.budget_rub)} · Срок: {need.deadline_date}
                </span>
                <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

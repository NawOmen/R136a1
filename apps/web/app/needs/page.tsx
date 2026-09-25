"use client";

// Мои потребности (GET /needs/mine): статус, объём, бюджет, срок,
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
  const [repeatId, setRepeatId] = useState<string | null>(null);
  const [repeating, setRepeating] = useState(false);

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

  async function repeat(need: Need) {
    const token = getToken(); if (!token) return;
    setRepeating(true); setError(null);
    try {
      const deadline = new Date(); deadline.setDate(deadline.getDate() + 30);
      const deadlineDate = deadline.toISOString().slice(0, 10);
      const storageKey = `porukam:repeat:${need.id}:${deadlineDate}`;
      const requestKey = sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
      sessionStorage.setItem(storageKey, requestKey);
      const copy = await marketplace.repeatNeed(token, need.id, deadlineDate, requestKey);
      sessionStorage.removeItem(storageKey);
      setNeeds((current) => [copy, ...current]); setRepeatId(null);
    } catch (err) { setError(err instanceof ApiError ? err.message : "Не удалось повторить потребность."); }
    finally { setRepeating(false); }
  }

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
            <li key={need.id} className="company-item repeat-order">
              <Link href={`/needs/${need.id}`} className="company-item">
                <span className="company-item__name">
                  {need.category} · {formatUnits(need.volume_units)}
                </span>
                <span className="company-meta">
                  Бюджет: {formatRub(need.budget_rub)} · Срок: {need.deadline_date}
                </span>
                <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
              </Link>
              {repeatId === need.id ? <div className="repeat-confirm"><span>Создать новый черновик со сроком +30 дней? Файлы, цены, допуск поставщика и прежние согласия не переносятся. Перед публикацией проверьте характеристики, адрес и бюджет.</span><button className="btn btn-primary btn-sm" disabled={repeating} onClick={() => void repeat(need)}>Да, создать</button><button className="btn btn-secondary btn-sm" onClick={() => setRepeatId(null)}>Отмена</button></div> : <button className="btn btn-secondary btn-sm" onClick={() => setRepeatId(need.id)}>Повторить заказ</button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

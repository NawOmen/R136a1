"use client";

// Лента открытых потребностей для продавца (GET /needs).
// У каждой — кнопка «Предложить условия»: форма (цена, объём, срок) →
// POST /needs/{id}/offers.

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  formatCharacteristics,
  formatUnits,
  marketplace,
  NeedFeedItem,
  NEED_STATUS_LABELS,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

export default function SellerRequestsPage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const [needs, setNeeds] = useState<NeedFeedItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [openFormId, setOpenFormId] = useState<string | null>(null);
  const [price, setPrice] = useState("");
  const [units, setUnits] = useState("");
  const [leadTime, setLeadTime] = useState("");
  const [submittedIds, setSubmittedIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    marketplace
      .getNeedsFeed(token, companyId)
      .then((list) => {
        if (!cancelled) setNeeds(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Не удалось загрузить запросы.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  function toggleForm(needId: string) {
    setOpenFormId((current) => (current === needId ? null : needId));
    setPrice("");
    setUnits("");
    setLeadTime("");
    setError(null);
  }

  async function handleOffer(event: FormEvent<HTMLFormElement>, need: NeedFeedItem) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;
    setSubmitting(true);
    setError(null);
    try {
      await marketplace.createOffer(token, need.id, {
        company_id: company.id,
        price_rub: Number(price),
        available_units: Number(units),
        lead_time_days: Number(leadTime),
      });
      setSubmittedIds((current) => new Set(current).add(need.id));
      setOpenFormId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить предложение.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Подходящие запросы</h1>
        <div className="alert alert-error">{meError}</div>
        <Link href="/login" className="btn btn-secondary">
          На страницу входа
        </Link>
      </div>
    );
  }

  if (available.length === 0) {
    return (
      <div>
        <h1 className="page-title">Подходящие запросы</h1>
        <div className="alert alert-error">
          У вас нет компании с правом «Продаю». Создайте компанию и включите режим продажи.
        </div>
        <div className="actions">
          <Link href="/company/new" className="btn btn-primary">
            Создать компанию
          </Link>
          <Link href="/dashboard" className="btn btn-secondary">
            На главную
          </Link>
        </div>
      </div>
    );
  }

  const openNeeds = needs.filter((need) => need.status === "open_for_offers");

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Подходящие запросы</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Открытые потребности покупателей — предложите свои условия</p>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="seller_company">Компания</label>
          <select id="seller_company" value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      {!loaded ? (
        <p className="hint">Загрузка запросов...</p>
      ) : openNeeds.length === 0 ? (
        <p className="hint">Открытых запросов пока нет.</p>
      ) : (
        <ul className="company-list">
          {openNeeds.map((need) => (
            <li key={need.id} className="card">
              <div className="company-row">
                <div>
                  <div className="company-item__name">
                    {need.category} · {formatUnits(need.volume_units)}
                  </div>
                  <div className="company-meta">
                    {formatCharacteristics(need.characteristics)}
                  </div>
                  <div className="company-meta">Срок: {need.deadline_date}</div>
                </div>
                <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
              </div>

              {submittedIds.has(need.id) ? (
                <p className="hint mode-hint">Предложение отправлено. Ожидайте решения покупателя.</p>
              ) : openFormId === need.id ? (
                <form className="card" style={{ marginTop: 12 }} onSubmit={(event) => void handleOffer(event, need)}>
                  <div className="field">
                    <label htmlFor={`offer_price_${need.id}`}>
                      Цена за единицу, ₽<span className="req">*</span>
                    </label>
                    <input
                      id={`offer_price_${need.id}`}
                      type="number"
                      min="0"
                      step="0.01"
                      value={price}
                      onChange={(event) => setPrice(event.target.value)}
                      placeholder="Например, 11.2"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`offer_units_${need.id}`}>
                      Доступный объём, шт.<span className="req">*</span>
                    </label>
                    <input
                      id={`offer_units_${need.id}`}
                      type="number"
                      min="1"
                      value={units}
                      onChange={(event) => setUnits(event.target.value)}
                      placeholder="Например, 48000"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`offer_lead_${need.id}`}>
                      Срок производства, дней<span className="req">*</span>
                    </label>
                    <input
                      id={`offer_lead_${need.id}`}
                      type="number"
                      min="1"
                      value={leadTime}
                      onChange={(event) => setLeadTime(event.target.value)}
                      placeholder="Например, 9"
                      required
                    />
                  </div>
                  <div className="actions">
                    <button type="submit" className="btn btn-primary" disabled={submitting}>
                      {submitting ? "Отправляем..." : "Отправить предложение"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => toggleForm(need.id)}
                    >
                      Отмена
                    </button>
                  </div>
                </form>
              ) : (
                <div className="actions">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => toggleForm(need.id)}>
                    Предложить условия
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

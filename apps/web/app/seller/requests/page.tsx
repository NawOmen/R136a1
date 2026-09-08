"use client";

// Лента открытых потребностей для продавца (GET /needs).
// У каждой — кнопка «Предложить условия»: форма (цена, объём, срок) →
// POST /needs/{id}/offers.

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import { agents, FactValue } from "../../lib/agents";
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
  const [deliveryCost, setDeliveryCost] = useState("0");
  const [moq, setMoq] = useState("");
  const [submittedIds, setSubmittedIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");

  useEffect(() => {
    setQuery(new URLSearchParams(window.location.search).get("q") ?? "");
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
    setDeliveryCost("0");
    setMoq("");
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
        delivery_cost_rub: Number(deliveryCost),
        moq_units: Number(moq || 1),
      });
      setSubmittedIds((current) => new Set(current).add(need.id));
      setOpenFormId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить предложение.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExplain(need: NeedFeedItem) {
    const token = getToken();
    if (!token || !company) return;
    const requirements: Record<string, FactValue> = {};
    for (const [key, value] of Object.entries(need.characteristics)) {
      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean" ||
        (Array.isArray(value) && value.every((item) => typeof item === "string"))
      ) {
        requirements[key] = value as FactValue;
      }
    }
    setExplainingId(need.id);
    setError(null);
    try {
      const result = await agents.explainSellerMatch(
        token,
        company.id,
        need.category,
        requirements,
      );
      setExplanations((current) => ({
        ...current,
        [need.id]: `${result.reasons.join(" ")} ${result.explanation}`,
      }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось объяснить совпадение.");
    } finally {
      setExplainingId(null);
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

  const normalizedQuery = query.trim().toLocaleLowerCase("ru");
  const openNeeds = needs.filter((need) =>
    ["open_for_offers", "waiting_for_match", "coalition_candidate"].includes(need.status) &&
    (!normalizedQuery || `${need.category} ${formatCharacteristics(need.characteristics)}`.toLocaleLowerCase("ru").includes(normalizedQuery)),
  );

  return (
    <div className="market-page">
      <header className="market-page__head">
        <div><span className="eyebrow">Рынок спроса</span><h1>Потребности покупателей</h1><p>Реальные запросы российских компаний — предложите производство на своих условиях</p></div>
        <Link href="/seller/opportunities" className="btn btn-secondary">Аналитика спроса</Link>
      </header>
      <div className="catalog-toolbar"><label className="catalog-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Категория или характеристика" aria-label="Поиск потребностей" /></label><span className="result-count">{openNeeds.length} открытых запросов</span></div>

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
        <ul className="demand-grid">
          {openNeeds.map((need) => (
            <li key={need.id} className="demand-card">
              <div className="demand-card__top"><span className="demand-kind">Производство</span><span className="demand-deadline">до {need.deadline_date}</span></div>
              <h2>{need.category}</h2>
              <p className="demand-description">{formatCharacteristics(need.characteristics)}</p>
              <dl className="demand-facts"><div><dt>Необходимый объём</dt><dd>{formatUnits(need.volume_units)}</dd></div><div><dt>Статус запроса</dt><dd>{NEED_STATUS_LABELS[need.status]}</dd></div></dl>

              {explanations[need.id] && (
                <p className="match-explanation"><b>Почему подходит</b>{explanations[need.id]}</p>
              )}

              {submittedIds.has(need.id) ? (
                <p className="hint mode-hint">Предложение отправлено. Ожидайте решения покупателя.</p>
              ) : openFormId === need.id ? (
                <form className="inline-offer" onSubmit={(event) => void handleOffer(event, need)}>
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
                    <label htmlFor={`offer_moq_${need.id}`}>
                      MOQ предложения, шт.<span className="req">*</span>
                    </label>
                    <input
                      id={`offer_moq_${need.id}`}
                      type="number"
                      min="1"
                      value={moq}
                      onChange={(event) => setMoq(event.target.value)}
                      placeholder="Например, 5000"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`offer_delivery_${need.id}`}>
                      Логистика, ₽<span className="req">*</span>
                    </label>
                    <input
                      id={`offer_delivery_${need.id}`}
                      type="number"
                      min="0"
                      step="0.01"
                      value={deliveryCost}
                      onChange={(event) => setDeliveryCost(event.target.value)}
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
                <div className="demand-actions">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={explainingId === need.id}
                    onClick={() => void handleExplain(need)}
                  >
                    {explainingId === need.id ? "Проверяю..." : "Почему подходит?"}
                  </button>
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

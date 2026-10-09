"use client";
import CommercialTermsFields, { emptyCommercialTerms } from "../../components/CommercialTermsFields";
import type { CommercialTerms } from "../../lib/marketplace";

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
  itemUnit,
  marketplace,
  NeedFeedItem,
  NEED_STATUS_LABELS,
  OfferDraft,
  Product,
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
  const [products, setProducts] = useState<Product[]>([]);
  const [resourceKind, setResourceKind] = useState<"capacity" | "stock">("capacity");
  const [productId, setProductId] = useState("");
  const [commercialTerms, setCommercialTerms] = useState<CommercialTerms>(emptyCommercialTerms);
  const [price, setPrice] = useState("");
  const [units, setUnits] = useState("");
  const [leadTime, setLeadTime] = useState("");
  const [deliveryCost, setDeliveryCost] = useState("");
  const [moq, setMoq] = useState("");
  const [submittedIds, setSubmittedIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [draftingId, setDraftingId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, OfferDraft>>({});
  const [requestKeys, setRequestKeys] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Record<string, { inputKey: string; blockers: string[]; warnings: string[]; missing: string[] }>>({});
  const [confirming, setConfirming] = useState(false);

  function offerInput(need: NeedFeedItem) {
    return {
      company_id: company!.id,
      commercial_terms: commercialTerms,
      price_rub: price,
      available_units: Number(units),
      lead_time_days: Number(leadTime),
      delivery_cost_rub: commercialTerms.delivery_method === "separate" ? (deliveryCost || null) : commercialTerms.delivery_method === "unknown" ? null : "0",
      moq_units: Number(moq || 1),
      draft_id: drafts[need.id]?.id,
      resource_kind: resourceKind,
      product_id: productId || undefined,
      price_tiers: drafts[need.id]?.payload.price_tiers ?? [],
    };
  }

  useEffect(() => {
    setQuery(new URLSearchParams(window.location.search).get("q") ?? "");
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setDrafts({}); setExplanations({}); setSubmittedIds(new Set()); setOpenFormId(null); setProducts([]);
    void marketplace.getCompanyProducts(token, companyId).then(items=>{if(!cancelled)setProducts(items);}).catch((e:Error)=>{if(!cancelled)setError(e.message);});
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
    const draft = drafts[needId];
    setRequestKeys((current) => current[needId] ? current : { ...current, [needId]: crypto.randomUUID() });
    setResourceKind(draft?.payload.resource_kind ?? "capacity");
    setProductId(draft?.payload.product_id ?? "");
    setCommercialTerms(emptyCommercialTerms);
    setOpenFormId((current) => (current === needId ? null : needId));
    setPrice(draft?.payload.price_rub != null ? String(draft.payload.price_rub) : "");
    setUnits(draft?.payload.available_units != null ? String(draft.payload.available_units) : "");
    setLeadTime(draft?.payload.lead_time_days != null ? String(draft.payload.lead_time_days) : "");
    setDeliveryCost(
      draft?.payload.delivery_cost_rub != null ? String(draft.payload.delivery_cost_rub) : "",
    );
    setMoq(draft?.payload.moq_units != null ? String(draft.payload.moq_units) : "");
    setError(null);
  }

  function inputKey(need: NeedFeedItem): string {
    return JSON.stringify({ ...offerInput(need), company: company?.id, draft: drafts[need.id]?.id ?? null });
  }

  async function handleOffer(event: FormEvent<HTMLFormElement>, need: NeedFeedItem) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;
    const requestKey = requestKeys[need.id] ?? crypto.randomUUID();
    setRequestKeys((current) => current[need.id] ? current : { ...current, [need.id]: requestKey });
    setSubmitting(true);
    setError(null);
    try {
      const preview = await marketplace.previewOfferSend(token, need.id, { ...offerInput(need), request_key: requestKey });
      setChecks((current) => ({ ...current, [need.id]: { inputKey: inputKey(need), ...preview } }));
      if (preview.blockers.length > 0) {
        setError(`Отправка заблокирована: ${preview.blockers.join("; ")}`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось проверить условия.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirmOffer(need: NeedFeedItem) {
    const token = getToken();
    if (!token || !company) return;
    const requestKey = requestKeys[need.id] ?? crypto.randomUUID();
    setRequestKeys((current) => current[need.id] ? current : { ...current, [need.id]: requestKey });
    setConfirming(true);
    setError(null);
    try {
      const sent = await marketplace.createOffer(token, need.id, { ...offerInput(need), request_key: requestKey });
      const warnings = sent.sending_warnings ?? [];
      if (warnings.length > 0) {
        setError(`Предложение отправлено, но проверьте недостающее: ${warnings.join("; ")}. Допуск подтвердят при выборе покупателем.`);
      } else {
        setSubmittedIds((current) => new Set(current).add(need.id));
        setOpenFormId(null);
        setChecks((current) => { const rest = { ...current }; delete rest[need.id]; return rest; });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить предложение.");
    } finally {
      setConfirming(false);
    }
  }

  async function handlePrepareDraft(need: NeedFeedItem) {
    const token = getToken();
    if (!token || !company) return;
    setDraftingId(need.id);
    setError(null);
    try {
      const draft = await marketplace.prepareOfferDraft(token, need.id, company.id);
      setDrafts((current) => ({ ...current, [need.id]: draft }));
      setRequestKeys((current) => current[need.id] ? current : { ...current, [need.id]: crypto.randomUUID() });
      // Черновик заполняет форму, но человек проверяет и при необходимости правит значения.
      setOpenFormId(need.id);
      setResourceKind(draft.payload.resource_kind);
      setProductId(draft.payload.product_id ?? "");
      setPrice(draft.payload.price_rub != null ? String(draft.payload.price_rub) : "");
      setUnits(draft.payload.available_units != null ? String(draft.payload.available_units) : "");
      setMoq(draft.payload.moq_units != null ? String(draft.payload.moq_units) : "");
      setLeadTime(draft.payload.lead_time_days != null ? String(draft.payload.lead_time_days) : "");
      setDeliveryCost(draft.payload.delivery_cost_rub != null ? String(draft.payload.delivery_cost_rub) : "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось подготовить черновик.");
    } finally {
      setDraftingId(null);
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
    (!normalizedQuery || `${need.category} ${formatCharacteristics(need.characteristics, need.category_profile)}`.toLocaleLowerCase("ru").includes(normalizedQuery)),
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
              <p className="demand-description">{formatCharacteristics(need.characteristics, need.category_profile)}</p>
              <dl className="demand-facts"><div><dt>Необходимый объём</dt><dd>{formatUnits(need.volume_units, itemUnit(need.characteristics))}</dd></div><div><dt>Статус запроса</dt><dd>{NEED_STATUS_LABELS[need.status]}</dd></div></dl>

              {explanations[need.id] && (
                <p className="match-explanation"><b>Почему подходит</b>{explanations[need.id]}</p>
              )}

              {drafts[need.id] && (
                <div className="draft-panel">
                  <p className="draft-panel__title">
                    Черновик КП подготовлен агентом — проверьте значения и подтвердите отправку
                  </p>
                  <ul className="draft-fields">
                    {drafts[need.id].fields.map((field) => (
                      <li key={field.name}>
                        <b>{field.label}:</b>{" "}
                        {field.value != null ? String(field.value) : "нужно указать"}
                        <span className="draft-source"> источник: {field.source}</span>
                        {!field.confirmed && <span className="draft-manual"> решение человека</span>}
                        {field.note && <span className="draft-note"> {field.note}</span>}
                      </li>
                    ))}
                  </ul>
                  {drafts[need.id].missing.length > 0 && (
                    <p className="draft-missing">
                      Заполните перед отправкой: {drafts[need.id].missing.join("; ")}
                    </p>
                  )}
                  {drafts[need.id].warnings.map((warning) => (
                    <p className="draft-warning" key={warning}>
                      {warning}
                    </p>
                  ))}
                </div>
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
                      step="any"
                      value={price}
                      onChange={(event) => setPrice(event.target.value)}
                      placeholder="Например, 11.2"
                      required
                    />
                  </div>
                  <div className="field"><label htmlFor={`offer_resource_${need.id}`}>Источник доступного объёма</label><select id={`offer_resource_${need.id}`} value={resourceKind} disabled={Boolean(drafts[need.id])} onChange={e=>setResourceKind(e.target.value as "stock" | "capacity")}><option value="capacity">Календарь производства</option><option value="stock">Остаток конкретного товара</option></select><p className="hint">Система проверит свободный ресурс при подтверждении сделки. Объём, уже занятый другими заказами или резервом, недоступен.</p></div>
                  {resourceKind === "stock" && <div className="field"><label htmlFor={`offer_product_${need.id}`}>Товар на складе</label><select id={`offer_product_${need.id}`} required value={productId} disabled={Boolean(drafts[need.id])} onChange={e=>setProductId(e.target.value)}><option value="">Выберите товар</option>{products.map(product=><option key={product.id} value={product.id}>{product.name}</option>)}</select></div>}
                  <div className="field">
                    <label htmlFor={`offer_units_${need.id}`}>
                      Доступный объём, {itemUnit(need.characteristics)}<span className="req">*</span>
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
                      MOQ предложения, {itemUnit(need.characteristics)}<span className="req">*</span>
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
                  <CommercialTermsFields value={commercialTerms} onChange={setCommercialTerms} disabled={submitting} />
                  <div className="field">
                    <label htmlFor={`offer_delivery_${need.id}`}>
                      Отдельная доставка, ₽<span className="req">*</span>
                    </label>
                    <input
                      id={`offer_delivery_${need.id}`}
                      type="number"
                      min="0"
                      step="0.01"
                      disabled={commercialTerms.delivery_method !== "separate"}
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
                      {submitting ? "Проверяем..." : "Проверить условия"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => toggleForm(need.id)}
                    >
                      Отмена
                    </button>
                  </div>
                  {checks[need.id] && (
                    <div className="card">
                      <h3>Проверка перед отправкой</h3>
                      {checks[need.id].missing.length > 0 && <>
                        <p className="hint">Не заполнено в черновике:</p>
                        <ul>{checks[need.id].missing.map((item) => <li key={item}>{item}</li>)}</ul>
                      </>}
                      {checks[need.id].warnings.length > 0 && <>
                        <p className="hint">Предупреждения (не блокируют, допуск проверят при выборе):</p>
                        <ul>{checks[need.id].warnings.map((item) => <li key={item}>{item}</li>)}</ul>
                      </>}
                      {checks[need.id].inputKey !== inputKey(need) ? (
                        <div className="alert alert-error">Условия изменились после проверки. Проверьте условия заново.</div>
                      ) : checks[need.id].blockers.length === 0 ? (
                        <button type="button" className="btn btn-success" disabled={confirming || submitting}
                          onClick={() => void handleConfirmOffer(need)}>
                          {confirming ? "Отправляем..." : "Подтвердить отправку КП"}
                        </button>
                      ) : (
                        <div className="alert alert-error">Отправка заблокирована, исправьте условия выше.</div>
                      )}
                    </div>
                  )}
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
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={draftingId === need.id}
                    onClick={() => void handlePrepareDraft(need)}
                  >
                    {draftingId === need.id ? "Готовлю..." : "Подготовить черновик КП"}
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

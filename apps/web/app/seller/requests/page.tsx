"use client";
import OfferResourceStatus, { type ResourceCheck } from "../../components/OfferResourceStatus";
import MoneyInput from "../../components/MoneyInput";
import { formatDate } from "../../lib/dates";
import { russianMessage } from "../../lib/russianMessages";
import CommercialTermsFields, { emptyCommercialTerms } from "../../components/CommercialTermsFields";
import { moneyInputValue } from "../../lib/money";
import type { CommercialTerms } from "../../lib/marketplace";

// Лента открытых потребностей для продавца (GET /needs).
// У каждой — кнопка «Предложить условия»: форма (цена, объём, срок) →
// POST /needs/{id}/offers.

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  formatCharacteristics,
  formatRub,
  formatUnits,
  itemUnit,
  marketplace,
  NeedFeedItem,
  NEED_STATUS_LABELS,
  OfferDraft,
  Product,
  Offer,
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
  const [priceEdited, setPriceEdited] = useState(false);
  const [units, setUnits] = useState("");
  const [leadTime, setLeadTime] = useState("");
  const [deliveryCost, setDeliveryCost] = useState("");
  const [moq, setMoq] = useState("");
  const [ownOffers, setOwnOffers] = useState<Record<string, Offer>>({});
  const [offersLoaded, setOffersLoaded] = useState(false);
  const [editingOffer, setEditingOffer] = useState<Offer | null>(null);
  const [resourceCheck, setResourceCheck] = useState<ResourceCheck | null>(null);
  const resourceKey = `${openFormId}:${companyId}:${resourceKind}:${productId}`;
  const resourceReady = resourceCheck?.key === resourceKey && !!resourceCheck.value && !resourceCheck.value.blockers.length && Number(units) <= resourceCheck.value.free_units;
  const [submitting, setSubmitting] = useState(false);
  const [query, setQuery] = useState("");
  const [draftingId, setDraftingId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, OfferDraft>>({});
  const [requestKeys, setRequestKeys] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Record<string, { inputKey: string; blockers: string[]; warnings: string[]; missing: string[] }>>({});
  const [confirming, setConfirming] = useState(false);
  const [draftAttached, setDraftAttached] = useState(false);
  // A response for a closed form or another company must never reopen it.
  const formGeneration = useRef(0);

  function offerInput(need: NeedFeedItem) {
    return {
      company_id: company!.id,
      commercial_terms: commercialTerms,
      price_rub: price,
      available_units: Number(units),
      lead_time_days: Number(leadTime),
      delivery_cost_rub: commercialTerms.delivery_method === "separate" ? (deliveryCost || null) : commercialTerms.delivery_method === "unknown" ? null : "0",
      moq_units: Number(moq || 1),
      draft_id: draftAttached ? drafts[need.id]?.id : undefined,
      resource_kind: resourceKind,
      product_id: productId || undefined,
      // New prices are fixed. Unchanged legacy terms must retain their price scale.
      price_tiers: editingOffer && !priceEdited ? editingOffer.price_tiers : [],
    };
  }

  useEffect(() => {
    setQuery(new URLSearchParams(window.location.search).get("q") ?? "");
    formGeneration.current += 1;
    setDraftingId(null);
    setSubmitting(false);
    setConfirming(false);
    setChecks({});
    setRequestKeys({});
    setDraftAttached(false);
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setDrafts({}); setOwnOffers({}); setOffersLoaded(false); setEditingOffer(null); setOpenFormId(null); setProducts([]);
    void marketplace.getCompanyOffers(token, companyId).then(items => { if (!cancelled) {
      setOwnOffers(Object.fromEntries(items.map(offer => [offer.need_id, offer]))); setOffersLoaded(true);
    } }).catch((e: Error) => { if (!cancelled) setError(e.message); });
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
          setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить запросы.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
      formGeneration.current += 1;
    };
  }, [companyId]);

  function closeForm() {
    formGeneration.current += 1;
    setOpenFormId(null);
    setDraftingId(null);
    setError(null);
  }

  function fillForm(need: NeedFeedItem, draft?: OfferDraft) {
    setEditingOffer(null); setPriceEdited(false); setResourceCheck(null);
    setDraftAttached(Boolean(draft));
    setResourceKind(draft?.payload.resource_kind ?? "capacity");
    setProductId(draft?.payload.product_id ?? "");
    setCommercialTerms({ ...emptyCommercialTerms, expenses: [] });
    setPrice(draft?.payload.price_rub != null ? moneyInputValue(draft.payload.price_rub) : "");
    // Start with the buyer's requested quantity. A shortage must be explicit,
    // never silently converted into agreement to supply only part of the need.
    setUnits(String(need.volume_units));
    setLeadTime(draft?.payload.lead_time_days != null ? String(draft.payload.lead_time_days) : "");
    setDeliveryCost(draft?.payload.delivery_cost_rub != null ? moneyInputValue(draft.payload.delivery_cost_rub) : "");
    setMoq(draft?.payload.moq_units != null ? String(draft.payload.moq_units) : "");
    setRequestKeys((current) => ({ ...current, [need.id]: crypto.randomUUID() }));
    setChecks((current) => { const rest = { ...current }; delete rest[need.id]; return rest; });
    setOpenFormId(need.id);
  }

  function detachDraft() {
    // The server binds an attached draft to its original product and resource.
    // A manually selected source is a new proposal, checked independently.
    setDraftAttached(false);
  }

  function inputKey(need: NeedFeedItem): string {
    return JSON.stringify({ ...offerInput(need), company: company?.id, draft: drafts[need.id]?.id ?? null, offer: editingOffer?.id, revision: editingOffer?.revision });
  }

  async function handleOffer(event: FormEvent<HTMLFormElement>, need: NeedFeedItem) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company || submitting || confirming) return;
    if (!resourceReady) { setError("Подтвердите достаточный и актуальный ресурс перед отправкой."); return; }
    if (!commercialTerms.delivery_conditions?.trim() || commercialTerms.delivery_method === "unknown" || commercialTerms.tax_basis === "unknown") { setError("Укажите условия и место получения, способ доставки и налоговую базу."); return; }
    const requestKey = requestKeys[need.id] ?? crypto.randomUUID();
    setRequestKeys((current) => current[need.id] ? current : { ...current, [need.id]: requestKey });
    const generation = formGeneration.current;
    setSubmitting(true);
    setError(null);
    try {
      const preview = await marketplace.previewOfferSend(token, need.id, { ...offerInput(need), request_key: requestKey, ...(editingOffer ? {offer_id: editingOffer.id, expected_revision: editingOffer.revision} : {}) });
      if (generation !== formGeneration.current) return;
      setChecks((current) => ({ ...current, [need.id]: { inputKey: inputKey(need), ...preview } }));
      if (preview.blockers.length > 0) {
        setError(`Отправка заблокирована: ${preview.blockers.join("; ")}`);
      }
    } catch (err) {
      if (generation === formGeneration.current) setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось проверить условия.");
    } finally {
      if (generation === formGeneration.current) setSubmitting(false);
    }
  }

  async function handleConfirmOffer(need: NeedFeedItem) {
    const token = getToken();
    if (!token || !company || submitting || confirming) return;
    const check = checks[need.id];
    if (!check || check.blockers.length || check.inputKey !== inputKey(need) || !resourceReady) return;
    const generation = formGeneration.current;
    const requestKey = requestKeys[need.id] ?? crypto.randomUUID();
    setRequestKeys((current) => current[need.id] ? current : { ...current, [need.id]: requestKey });
    setConfirming(true);
    setError(null);
    try {
      const {company_id: _company, draft_id: _draft, ...changes} = offerInput(need);
      const sent = editingOffer
        ? await marketplace.updateOffer(token, editingOffer.id, { ...changes, product_id: productId || null, expected_revision: editingOffer.revision })
        : await marketplace.createOffer(token, need.id, { ...offerInput(need), request_key: requestKey });
      if (generation !== formGeneration.current) return;
      const warnings = sent.sending_warnings ?? [];
      setOwnOffers(current => ({ ...current, [need.id]: sent }));
      setEditingOffer(null);
      setOpenFormId(null);
      setChecks((current) => { const rest = { ...current }; delete rest[need.id]; return rest; });
      if (warnings.length > 0) {
        setError(`Предложение отправлено, но проверьте недостающее: ${warnings.join("; ")}. Допуск подтвердят при выборе покупателем.`);
      }
    } catch (err) {
      if (generation === formGeneration.current) setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось отправить предложение.");
    } finally {
      if (generation === formGeneration.current) setConfirming(false);
    }
  }

  async function handlePrepareDraft(need: NeedFeedItem) {
    const token = getToken();
    if (!token || !company || submitting || confirming || draftingId !== null) return;
    const generation = ++formGeneration.current;
    setOpenFormId(null);
    setDraftingId(need.id);
    setError(null);
    let existingChecked = false;
    try {
      const existing = (await marketplace.getOffers(token, need.id)).find(offer => offer.company_id === company.id && offer.status === "sent");
      if (generation !== formGeneration.current) return;
      existingChecked = true;
      if (existing) {
        if (!company.membership?.is_admin) { setError("Изменить отправленное КП может администратор компании."); return; }
        fillForm(need);
        setEditingOffer(existing); setDraftAttached(false);
        setOwnOffers(current => ({ ...current, [need.id]: existing }));
        setResourceKind(existing.resource_kind ?? "capacity"); setProductId(existing.product_id ?? "");
        setCommercialTerms({ ...emptyCommercialTerms, ...existing.commercial_terms, expenses: (existing.commercial_terms?.expenses ?? []).map(row => ({...row})) });
        setPrice(String(existing.price_rub)); setUnits(String(existing.available_units));
        setLeadTime(String(existing.lead_time_days)); setDeliveryCost(existing.delivery_cost_rub == null ? "" : String(existing.delivery_cost_rub)); setMoq(String(existing.moq_units));
        return;
      }
      const draft = await marketplace.prepareOfferDraft(token, need.id, company.id);
      if (generation !== formGeneration.current) return;
      setDrafts((current) => ({ ...current, [need.id]: draft }));
      fillForm(need, draft);
    } catch (err) {
      if (generation !== formGeneration.current) return;
      if (!existingChecked) { setError(err instanceof Error ? russianMessage(err.message) : "Не удалось проверить отправленное КП. Обновите страницу."); return; }
      // The manual path remains available when automatic preparation fails.
      setDrafts((current) => { const rest = { ...current }; delete rest[need.id]; return rest; });
      fillForm(need);
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось заполнить предложение. Укажите условия вручную.");
    } finally {
      if (generation === formGeneration.current) setDraftingId(null);
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
            В личный кабинет
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
        <div><span className="eyebrow">Рынок спроса</span><h1>Потребности покупателей</h1><p>Опубликованные запросы российских компаний — предложите производство на своих условиях</p></div>
        <div className="actions"><Link href="/seller/inquiries" className="btn btn-secondary">Переписка с покупателями</Link><Link href="/seller/opportunities" className="btn btn-secondary">Аналитика спроса</Link></div>
      </header>
      <div className="catalog-toolbar"><label className="catalog-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Категория или характеристика" aria-label="Поиск потребностей" /></label><span className="result-count">{openNeeds.length} открытых запросов</span></div>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="seller_company">Компания</label>
          <select id="seller_company" disabled={submitting || confirming} value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {error && <div role="alert" className="alert alert-error">{error}</div>}

      {!loaded ? (
        <p className="hint">Загрузка запросов...</p>
      ) : openNeeds.length === 0 ? (
        <p className="hint">Открытых запросов пока нет.</p>
      ) : (
        <ul className="demand-grid">
          {openNeeds.map((need) => (
            <li key={need.id} className={`demand-card${openFormId === need.id ? " demand-card--editing" : ""}`} data-need-id={need.id}>
              <div className="demand-card__top"><span className="demand-kind">Производство</span><span className="demand-deadline">до {formatDate(need.deadline_date)}</span></div>
              <h2>{need.category}</h2>
              <p className="demand-description">{formatCharacteristics(need.characteristics, need.category_profile)}</p>
              <dl className="demand-facts"><div><dt>Необходимый объём</dt><dd>{formatUnits(need.volume_units, itemUnit(need.characteristics))}</dd></div><div><dt>Статус запроса</dt><dd>{NEED_STATUS_LABELS[need.status]}</dd></div></dl>

              {ownOffers[need.id] && openFormId !== need.id && <p className="hint mode-hint">Предложение отправлено. Версия {ownOffers[need.id].revision}. {ownOffers[need.id].status === "sent" ? "Условия можно изменить до выбора покупателем." : "Предложение больше не редактируется."}</p>}
              {openFormId === need.id ? (
                <form className="inline-offer seller-offer" onSubmit={(event) => void handleOffer(event, need)}>
                  <div className="seller-offer__intro">
                    <h3>{editingOffer ? "Изменение условий предложения" : "Условия предложения"}</h3>
                    <p>Оставьте подходящие условия или измените любой пункт. Покупатель получит предложение только после вашего подтверждения.</p>
                    <p className="hint">{editingOffer?.price_tiers?.length && !priceEdited ? `Сохранены цены по объёму: ${editingOffer.price_tiers.map(tier => `от ${tier.min_units} ${itemUnit(need.characteristics)} — ${formatRub(tier.unit_price_rub)}`).join("; ")}. Изменение цены заменит эту шкалу фиксированной ценой.` : "Проверьте заполненные поля. Указанная цена фиксирована для этого предложения."}</p>
                    {editingOffer && <button type="button" className="btn btn-secondary btn-sm" disabled={submitting || confirming || draftingId !== null} onClick={() => void handlePrepareDraft(need)}>Загрузить актуальную версию КП</button>}
                  </div>
                  <fieldset className="seller-offer__fields" disabled={submitting || confirming}>
                  <legend className="visually-hidden">Редактируемые условия предложения</legend>
                  <div className="field">
                    <label htmlFor={`offer_price_${need.id}`}>
                      Цена за единицу, ₽<span className="req">*</span>
                    </label>
                    <MoneyInput
                      id={`offer_price_${need.id}`}
                      min="0.01"
                      value={price}
                      onChange={(event) => { setPrice(event.target.value); setPriceEdited(true); }}
                      placeholder="Например, 11.2"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`offer_units_${need.id}`}>
                      Объём предложения, {itemUnit(need.characteristics)}<span className="req">*</span>
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
                      Минимальная партия, {itemUnit(need.characteristics)}<span className="req">*</span>
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
                  <div className="field"><label htmlFor={`offer_resource_${need.id}`}>Источник доступного объёма</label><select id={`offer_resource_${need.id}`} value={resourceKind} onChange={e=>{if (e.target.value !== resourceKind) { detachDraft(); setProductId(""); } setResourceKind(e.target.value as "stock" | "capacity");}}><option value="capacity">Календарь производства</option><option value="stock">Остаток конкретного товара</option></select><p className="hint">Система проверит свободный ресурс при подтверждении сделки. Объём, уже занятый другими заказами или резервом, недоступен.</p></div>
                  {resourceKind === "stock" && <div className="field"><label htmlFor={`offer_product_${need.id}`}>Товар на складе</label><select id={`offer_product_${need.id}`} required value={productId} onChange={e=>{if (e.target.value !== productId) detachDraft(); setProductId(e.target.value);}}><option value="">Выберите товар</option>{products.map(product=><option key={product.id} value={product.id}>{product.name}</option>)}</select></div>}
                  <OfferResourceStatus needId={need.id} companyId={companyId} kind={resourceKind} productId={productId} units={Number(units)} category={need.category} subcategory={need.subcategory} onChange={setResourceCheck} />
                  <CommercialTermsFields requireReceipt value={commercialTerms} onChange={setCommercialTerms} disabled={submitting || confirming} />
                  <div className="field">
                    <label htmlFor={`offer_delivery_${need.id}`}>
                      Отдельная доставка, ₽<span className="req">*</span>
                    </label>
                    <MoneyInput
                      id={`offer_delivery_${need.id}`}
                      min="0"
                      disabled={commercialTerms.delivery_method !== "separate"}
                      value={deliveryCost}
                      onChange={(event) => setDeliveryCost(event.target.value)}
                      required
                    />
                  </div>
                  </fieldset>
                  <p className="hint seller-offer__wide">Уточните доставку и НДС перед отправкой.</p>
                  <div className="actions seller-offer__wide">
                    <button type="submit" className="btn btn-primary" disabled={submitting || confirming || !resourceReady}>
                      {submitting ? "Проверяем..." : "Проверить условия"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={submitting || confirming}
                      onClick={closeForm}
                    >
                      Отмена
                    </button>
                  </div>
                  {checks[need.id] && (
                    <div className="card seller-offer__wide">
                      <h3>Проверка перед отправкой</h3>
                      <p className="hint">Если условия подходят, подтвердите отправку. Для встречного предложения измените нужные поля выше и проверьте их заново.</p>
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
                        <button type="button" className="btn btn-success" disabled={confirming || submitting || !resourceReady}
                          onClick={() => void handleConfirmOffer(need)}>
                          {confirming ? "Отправляем..." : editingOffer ? "Подтвердить изменение КП" : "Подтвердить отправку КП"}
                        </button>
                      ) : (
                        <div className="alert alert-error">Отправка заблокирована, исправьте условия выше.</div>
                      )}
                    </div>
                  )}
                </form>
              ) : (
                <div className="demand-actions">
                  {ownOffers[need.id]?.status === "sent" && !company?.membership?.is_admin && <p className="hint">Изменить отправленное КП может администратор компании.</p>}
                  <button type="button" className="btn btn-primary btn-sm" disabled={!offersLoaded || draftingId !== null || submitting || confirming || !!(ownOffers[need.id] && (ownOffers[need.id].status !== "sent" || !company?.membership?.is_admin))} onClick={() => void handlePrepareDraft(need)}>
                    {draftingId === need.id ? "Загружаем условия..." : ownOffers[need.id]?.status === "sent" ? "Изменить условия" : "Предложить условия"}
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

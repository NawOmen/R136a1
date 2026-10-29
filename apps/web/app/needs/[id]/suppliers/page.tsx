"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import SupplierBoard from "../../../components/SupplierBoard";
import SupplierConversation from "../../../components/SupplierConversation";
import { Icon } from "../../../components/Icon";
import { getToken } from "../../../lib/api";
import { formatDate } from "../../../lib/dates";
import {
  formatRub,
  formatUnits,
  itemUnit,
  marketplace,
  Need,
  NeedFeedItem,
  NEED_STATUS_LABELS,
  Offer,
} from "../../../lib/marketplace";
import { russianMessage } from "../../../lib/russianMessages";
import { supplierWorkflow as api, type SupplierCandidate, type SupplierRequest } from "../../../lib/supplierWorkflow";
import { useMe } from "../../../lib/useMe";

// Подбор поставщиков — отдельная страница вместо блока «Поставщики и ответы».
// Две вкладки: карточки подходящих поставщиков и доска запросов с перепиской.
// Цена, объём и сделка остаются за человеком.

type SortKey = "relevance" | "price" | "lead";
type TabKey = "suppliers" | "board";

const SORT_LABELS: Record<SortKey, string> = {
  relevance: "Сначала подходящие",
  price: "Сначала дешёвые",
  lead: "Сначала быстрые",
};

const REQUEST_LABELS: Record<string, string> = {
  draft: "Черновик запроса",
  sent: "Запрос отправлен",
  replied: "Ответил",
  selected: "Выбран",
};

function offerOf(supplier: string, offers: Offer[]) {
  return offers.find(offer => offer.company_id === supplier) ?? null;
}

function requestOf(supplier: string, requests: SupplierRequest[]) {
  return requests.find(row => row.seller_company_id === supplier) ?? null;
}

export default function SupplierSelectionPage() {
  useMe();
  const params = useParams();
  const needId = typeof params.id === "string" ? params.id : "";
  const [need, setNeed] = useState<Need | NeedFeedItem | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [candidates, setCandidates] = useState<SupplierCandidate[]>([]);
  const [requests, setRequests] = useState<SupplierRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("relevance");
  const [onlyRelevant, setOnlyRelevant] = useState(true);
  const [tab, setTab] = useState<TabKey>("suppliers");
  const [openConversation, setOpenConversation] = useState<string | null>(null);

  async function load() {
    const token = getToken();
    if (!token || !needId) return;
    setLoading(true);
    setError(null);
    try {
      const current = await marketplace.getNeed(token, needId);
      setNeed(current);
      const owner = "company_id" in current ? current.company_id : null;
      const [offerList, supplierList, requestList] = await Promise.all([
        marketplace.getOffers(token, needId),
        owner ? api.candidates(token, needId, owner) : Promise.resolve([]),
        owner ? api.list(token, owner, needId) : Promise.resolve([]),
      ]);
      setOffers(offerList);
      setCandidates(supplierList);
      setRequests(requestList);
    } catch (err: unknown) {
      setError(err instanceof Error ? russianMessage(err.message) : "Не удалось загрузить подбор поставщиков.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [needId]);

  const companyId = need && "company_id" in need ? need.company_id : null;
  const canManage = Boolean(companyId && need && need.visibility === "open_anonymized");

  async function askQuote(supplier: string) {
    const token = getToken();
    if (!token || !need || !companyId) return;
    setBusy(supplier);
    setError(null);
    try {
      const created = await api.create(token, needId, companyId, supplier, need.revision);
      setRequests(current => [created, ...current]);
      setOpenConversation(created.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? russianMessage(err.message) : "Не удалось отправить запрос поставщику.");
    } finally {
      setBusy(null);
    }
  }

  const visible = useMemo(() => {
    const text = query.trim().toLocaleLowerCase("ru");
    const rows = candidates
      .filter(item => (onlyRelevant ? item.relevant : true))
      .filter(item => !text || `${item.company_name} ${item.specialization.join(" ")} ${item.products.join(" ")}`.toLocaleLowerCase("ru").includes(text));
    const price = (item: SupplierCandidate) => {
      const offer = offerOf(item.company_id, offers);
      return offer ? Number(offer.price_rub) : Number.POSITIVE_INFINITY;
    };
    const lead = (item: SupplierCandidate) => {
      const offer = offerOf(item.company_id, offers);
      return offer ? offer.lead_time_days : Number.POSITIVE_INFINITY;
    };
    return [...rows].sort((left, right) => {
      if (sort === "price") return price(left) - price(right);
      if (sort === "lead") return lead(left) - lead(right);
      const byOffer = (offerOf(left.company_id, offers) ? 0 : 1) - (offerOf(right.company_id, offers) ? 0 : 1);
      return byOffer || Number(right.relevant) - Number(left.relevant) || left.company_name.localeCompare(right.company_name, "ru");
    });
  }, [candidates, offers, onlyRelevant, query, sort]);

  const unit = need ? itemUnit(need.characteristics) : "шт.";
  const withOffer = candidates.filter(item => offerOf(item.company_id, offers)).length;

  return <div className="supplier-selection">
    <header className="supplier-selection__head">
      <div>
        <p className="supplier-selection__eyebrow">{need ? `Потребность · ${NEED_STATUS_LABELS[need.status]}` : "Потребность"}</p>
        <h1 className="page-title">Подбор поставщиков</h1>
        <p className="subtitle">{need ? `${need.category}${need.subcategory ? ` · ${need.subcategory}` : ""} · ${formatUnits(need.volume_units, unit)} · до ${formatDate(need.deadline_date)}` : "Загружаем условия потребности…"}</p>
      </div>
      <Link className="btn btn-secondary btn-sm supplier-selection__back" href={`/needs/${needId}`}>К потребности</Link>
    </header>

    {error && <div className="alert alert-error" role="alert">{error} <button type="button" className="btn btn-secondary btn-sm" onClick={() => void load()}>Повторить</button></div>}

    <div className="supplier-tabs" role="tablist" aria-label="Режим подбора">
      <button type="button" role="tab" aria-selected={tab === "suppliers"} onClick={() => setTab("suppliers")}>Подбор поставщиков <span>{visible.length}</span></button>
      <button type="button" role="tab" aria-selected={tab === "board"} onClick={() => setTab("board")}>Доска запросов <span>{requests.length}</span></button>
    </div>

    {tab === "suppliers" ? <>
      <div className="supplier-filters">
        <div className="field supplier-filters__search"><label htmlFor="supplier-search">Поиск</label><input id="supplier-search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Поставщик или товар" /></div>
        <div className="field"><label htmlFor="supplier-sort">Сортировка</label><select id="supplier-sort" value={sort} onChange={event => setSort(event.target.value as SortKey)}>{(Object.keys(SORT_LABELS) as SortKey[]).map(key => <option key={key} value={key}>{SORT_LABELS[key]}</option>)}</select></div>
        <label className="supplier-filters__check"><input type="checkbox" checked={onlyRelevant} onChange={event => setOnlyRelevant(event.target.checked)} />Только по категории</label>
        <p className="supplier-filters__count" role="status">Найдено {visible.length} из {candidates.length}{withOffer ? ` · с ценой ${withOffer}` : ""}</p>
      </div>

      {loading ? <p className="hint" role="status">Загружаем поставщиков…</p>
        : visible.length === 0
          ? <div className="supplier-empty"><Icon name="search" size={22} /><p>{candidates.length === 0 ? "Проверенных поставщиков этой категории пока нет." : "Ничего не найдено. Измените поиск или покажите всех поставщиков."}</p></div>
          : <ul className="supplier-grid">
              {visible.map(item => {
                const offer = offerOf(item.company_id, offers);
                const request = requestOf(item.company_id, requests);
                const total = offer ? Number(offer.price_rub) * Number(need?.volume_units ?? 0) : null;
                return <li key={item.company_id} className="supplier-tile">
                  <div className="supplier-tile__top">
                    <div className="supplier-tile__name">
                      <h2>{item.company_name}</h2>
                      <div className="supplier-tile__badges">
                        {item.relevant && <span className="badge badge-verified">По категории</span>}
                        {offer && <span className="badge badge-open_for_offers">Есть предложение</span>}
                        {request && <span className="badge badge-draft">{REQUEST_LABELS[request.status] ?? "Запрос"}</span>}
                      </div>
                    </div>
                    <div className="supplier-tile__price">
                      <strong>{offer ? formatRub(offer.price_rub) : "—"}</strong>
                      <small>{offer ? `за ${unit}` : "цена по запросу"}</small>
                    </div>
                  </div>

                  <dl className="supplier-tile__facts">
                    <div><dt>Срок</dt><dd>{offer ? `${offer.lead_time_days} дн.` : "—"}</dd></div>
                    <div><dt>Остаток</dt><dd>{offer ? formatUnits(offer.available_units, unit) : "—"}</dd></div>
                    <div><dt>Мин. заказ</dt><dd>{offer ? formatUnits(offer.moq_units, unit) : "—"}</dd></div>
                  </dl>

                  {item.products.length > 0 && <div className="supplier-tile__products" title={item.products.join(", ")}>{item.products.slice(0, 3).map(product => <span key={product} className="product-chip">{product}</span>)}{item.products.length > 3 && <span className="product-chip product-chip--more">+{item.products.length - 3}</span>}</div>}

                  {total !== null && <p className="supplier-tile__total">За весь объём: <strong>{formatRub(total)}</strong></p>}

                  <div className="supplier-tile__actions">
                    <Link className="btn btn-secondary btn-sm" href={`/producers/${item.company_id}`}>О поставщике</Link>
                    {request
                      ? <button type="button" className="btn btn-primary btn-sm" aria-expanded={openConversation === request.id} onClick={() => setOpenConversation(openConversation === request.id ? null : request.id)}>{openConversation === request.id ? "Скрыть переписку" : "Переписка"}</button>
                      : canManage && <button type="button" className="btn btn-primary btn-sm" disabled={busy === item.company_id} onClick={() => void askQuote(item.company_id)}>{busy === item.company_id ? "Отправляем…" : "Запросить КП"}</button>}
                  </div>

                  {request && openConversation === request.id && companyId && <div className="supplier-tile__conversation">
                    <SupplierConversation key={`${request.id}:${request.revision}`} row={request} companyId={companyId} canManage={canManage} onChanged={load} />
                  </div>}
                </li>;
              })}
            </ul>}
    </> : (
      companyId
        ? <SupplierBoard key={`${needId}:${companyId}:${need?.revision ?? 0}`} needId={needId} companyId={companyId} needRevision={need?.revision ?? 1} canManage={canManage} />
        : <p className="hint">Доска запросов доступна покупателю этой потребности.</p>
    )}
  </div>;
}

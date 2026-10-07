"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import DealExecutionPanel from "../components/DealExecutionPanel";
import { api, Company, getToken } from "../lib/api";
import { Deal, DealCheckpoint, DealMessage, DeliveryArrangement, formatRub, formatUnits, marketplace } from "../lib/marketplace";

const CHECKPOINT_LABELS = { production: "Производство", shipment: "Отгрузка", delivery: "Доставка" } as const;

export default function DealsPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [selected, setSelected] = useState<Deal | null>(null);
  const [actingCompanyId, setActingCompanyId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const partyCompanies = selected ? companies.filter(c => c.id === selected.buyer_company_id || c.id === selected.seller_company_id) : [];
  const companyId = partyCompanies.some(c => c.id === actingCompanyId) ? actingCompanyId : partyCompanies[0]?.id;

  useEffect(() => {
    let alive = true;
    const token = getToken();
    setLoading(true); setError(null);
    if (!token) { setLoading(false); setError("Войдите в аккаунт, чтобы открыть сделки."); return; }
    Promise.all([api.me(token), marketplace.getMyDeals(token)]).then(([me, list]) => {
      if (!alive) return;
      setCompanies(me.companies); setDeals(list);
      const requested = new URLSearchParams(window.location.search).get("deal");
      setSelected(list.find(item => item.id === requested) ?? list[0] ?? null);
    }).catch((e: Error) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [retry]);

  return <div><h1>Сделки и сообщения</h1><p className="subtitle">Переписка, организация получения и контрольные точки</p>
    {error && <div className="alert alert-error">{error} <button type="button" className="btn btn-secondary btn-sm" disabled={loading} onClick={() => setRetry(n => n + 1)}>Повторить загрузку</button></div>}
    <div className="deal-layout"><aside className="card"><h2>Мои сделки</h2>
      {loading ? <p className="hint" role="status">Загружаем сделки…</p> : deals.length === 0 ? !error && <p className="hint">Сделок пока нет.</p> : deals.map(deal => <button type="button" className="deal-button" key={deal.id} onClick={() => { setSelected(deal); setActingCompanyId(""); }}>{formatUnits(deal.units)} · {formatRub(deal.total_price_rub)}</button>)}
    </aside><div>{selected && companyId ? <DealWorkspace key={`${selected.id}:${companyId}`} selected={selected} companyId={companyId} partyCompanies={partyCompanies} onCompanyChange={setActingCompanyId} /> : !loading && !error && <section className="card"><h2>Переписка</h2><p className="hint">Выберите сделку.</p></section>}</div></div>
  </div>;
}

function DealWorkspace({ selected, companyId, partyCompanies, onCompanyChange }: {
  selected: Deal; companyId: string; partyCompanies: Company[]; onCompanyChange: (id: string) => void;
}) {
  const [messages, setMessages] = useState<DealMessage[]>([]);
  const [timeline, setTimeline] = useState<DealCheckpoint[]>([]);
  const [delivery, setDelivery] = useState<DeliveryArrangement | null>(null);
  const [draft, setDraft] = useState(""); const [weight, setWeight] = useState(""); const [volume, setVolume] = useState("");
  const [method, setMethod] = useState<DeliveryArrangement["method"]>("buyer_carrier");
  const [carrier, setCarrier] = useState(""); const [rating, setRating] = useState("5"); const [review, setReview] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false); const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string | null>(null);
  const alive = useRef(false); const sequence = useRef(0); const busy = useRef(false);
  const deliveryFormInitialized = useRef(false);
  const isBuyer = companyId === selected.buyer_company_id; const isSeller = companyId === selected.seller_company_id;

  const loadDeal = useCallback(async () => {
    const token = getToken();
    if (!token) throw new Error("Войдите в аккаунт, чтобы открыть сделку.");
    const request = ++sequence.current;
    setLoading(true);
    try {
      const [messageList, steps, arrangement] = await Promise.all([
        marketplace.getDealMessages(token, selected.id, companyId),
        marketplace.getDealTimeline(token, selected.id, companyId),
        marketplace.getDelivery(token, selected.id, companyId),
      ]);
      if (!alive.current || request !== sequence.current) return;
      setMessages(messageList); setTimeline(steps); setDelivery(arrangement); setLoaded(true);
      if (!deliveryFormInitialized.current) {
        setWeight(arrangement ? String(arrangement.weight_kg) : "");
        setVolume(arrangement ? String(arrangement.volume_m3) : "");
        setMethod(arrangement?.method ?? "buyer_carrier"); setCarrier(arrangement?.carrier_name ?? "");
        deliveryFormInitialized.current = true;
      }
    } finally { if (alive.current && request === sequence.current) setLoading(false); }
  }, [selected.id, companyId]);
  useEffect(() => {
    alive.current = true;
    void loadDeal().catch((e: Error) => { if (alive.current) setError(e.message); });
    return () => { alive.current = false; sequence.current += 1; };
  }, [loadDeal]);

  async function runAction(label: string, action: (token: string) => Promise<void>) {
    const token = getToken();
    if (busy.current || !loaded) return;
    if (!token) { setError("Войдите в аккаунт, чтобы продолжить."); return; }
    busy.current = true; setPending(label); setError(null);
    try { await action(token); }
    catch (e) { if (alive.current) setError(e instanceof Error ? e.message : "Не удалось выполнить действие."); }
    finally { busy.current = false; if (alive.current) setPending(null); }
  }
  async function send(event: FormEvent) {
    event.preventDefault(); if (!draft.trim()) return;
    await runAction("Отправляем сообщение…", async token => {
      await marketplace.sendDealMessage(token, selected.id, companyId, draft);
      if (!alive.current) return;
      setDraft(""); await loadDeal();
    });
  }
  async function completeCheckpoint(step: DealCheckpoint) {
    await runAction("Подтверждаем этап…", async token => {
      const steps = await marketplace.updateDealCheckpoint(token, selected.id, step.kind, companyId, true);
      if (alive.current) setTimeline(steps);
    });
  }
  async function saveDelivery(event: FormEvent) {
    event.preventDefault();
    await runAction("Сохраняем получение…", async token => {
      const arrangement = await marketplace.saveDelivery(token, selected.id, { company_id: companyId, weight_kg: Number(weight), volume_m3: Number(volume), method, carrier_name: carrier || undefined });
      if (alive.current) setDelivery(arrangement);
    });
  }
  async function submitReview(event: FormEvent) {
    event.preventDefault();
    await runAction("Публикуем отзыв…", async token => {
      await marketplace.createReview(token, selected.id, companyId, Number(rating), review);
      if (!alive.current) return;
      setReview(""); window.alert("Отзыв опубликован как отзыв по подтверждённой сделке.");
    });
  }

  return <div>
    {error && <div className="alert alert-error">{error} <button type="button" className="btn btn-secondary btn-sm" disabled={loading || pending !== null} onClick={() => { setError(null); void loadDeal().catch((e: Error) => { if (alive.current) setError(e.message); }); }}>Повторить загрузку</button></div>}
    {loading && <p className="hint" role="status">Загружаем данные сделки…</p>}
    {pending && <p className="hint" role="status">{pending}</p>}
    {loaded && <><section className="card"><div className="company-row"><h2>Таймлайн сделки</h2>{partyCompanies.length > 1 && <select aria-label="Компания в сделке" value={companyId} onChange={e => onCompanyChange(e.target.value)}>{partyCompanies.map(company => <option key={company.id} value={company.id}>{company.display_name}</option>)}</select>}</div><div className="deal-timeline">{timeline.map((step, index) => { const allowed = (step.kind === "delivery" && isBuyer) || (step.kind !== "delivery" && isSeller); return <div className={step.status === "completed" ? "timeline-step done" : "timeline-step"} key={step.id}><span>{step.status === "completed" ? "✓" : index + 1}</span><div><b>{CHECKPOINT_LABELS[step.kind]}</b><small>{step.completed_at ? new Date(step.completed_at).toLocaleString("ru-RU") : "Ожидает подтверждения"}</small></div>{step.status !== "completed" && allowed && <button type="button" className="btn btn-secondary btn-sm" disabled={pending !== null} onClick={() => void completeCheckpoint(step)}>Подтвердить</button>}</div>; })}</div><p className="hint">Производство и отгрузку подтверждает продавец, получение — покупатель. Этапы нельзя перескочить.</p></section>
    <DealExecutionPanel key={`${selected.id}:${companyId}:${timeline.map(s=>s.status).join(":")}`} dealId={selected.id} companyId={companyId} isBuyer={isBuyer} canManage={partyCompanies.find(c=>c.id===companyId)?.membership?.is_admin === true} />
    {isBuyer&&<section className="card"><h2>Организация получения</h2>{delivery&&<div className="alert alert-success">{delivery.classification_note}</div>}<p className="hint">ПоРукам фиксирует параметры и ответственных, но не оказывает перевозку. Перевозчика выбирает покупатель.</p><form className="form-grid" onSubmit={saveDelivery}><div className="field"><label>Вес партии, кг</label><input type="number" min="0.001" step="0.001" required value={weight} onChange={(e)=>setWeight(e.target.value)}/></div><div className="field"><label>Объём партии, м³</label><input type="number" min="0.001" step="0.001" required value={volume} onChange={(e)=>setVolume(e.target.value)}/></div><div className="field"><label>Способ</label><select value={method} onChange={(e)=>setMethod(e.target.value as DeliveryArrangement["method"])}><option value="buyer_carrier">Перевозчик покупателя</option><option value="self_pickup">Самовывоз</option><option value="seller_delivery">Доставка продавца по согласованию</option></select></div><div className="field"><label>Перевозчик {method==="buyer_carrier"?"":"(необязательно)"}</label><input type="text" required={method==="buyer_carrier"} value={carrier} onChange={(e)=>setCarrier(e.target.value)}/></div><button className="btn btn-primary" disabled={pending !== null}>Подтвердить способ получения</button></form></section>}
    <section className="card"><h2>Переписка</h2>{!selected?<p className="hint">Выберите сделку.</p>:<><div className="message-list">{messages.length===0?<p className="hint">Начните обсуждение условий.</p>:messages.map((m)=><p key={m.id}><b>{m.author_company_id===companyId?"Ваша компания":"Участник сделки"}</b><br/>{m.message}</p>)}</div><form onSubmit={send}><div className="field"><label htmlFor="deal-message">Сообщение</label><textarea id="deal-message" maxLength={2000} value={draft} onChange={(e)=>setDraft(e.target.value)} /></div><button className="btn btn-primary" disabled={pending !== null}>Отправить</button></form></>}</section>
    {timeline.at(-1)?.status==="completed"&&<section className="card"><h2>Отзыв по подтверждённой сделке</h2><form onSubmit={submitReview}><div className="field"><label>Оценка</label><select value={rating} onChange={(e)=>setRating(e.target.value)}>{[5,4,3,2,1].map((n)=><option key={n}>{n}</option>)}</select></div><div className="field"><label>Комментарий</label><textarea minLength={10} required value={review} onChange={(e)=>setReview(e.target.value)}/></div><button className="btn btn-primary" disabled={pending !== null}>Опубликовать отзыв</button></form></section>}</>}
  </div>;
}

"use client";
import { russianMessage } from "../../lib/russianMessages";
import { russianLabel } from "../../lib/presentation";
import CommercialTermsFields, { emptyCommercialTerms } from "../../components/CommercialTermsFields";
import type { CommercialTerms } from "../../lib/marketplace";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import { ApiError, formatRub, formatUnits, marketplace, PrimaryObligation, ReserveCommitment } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

export default function SellerReservesPage() {
  const { loading, error: meError, available, companyId, setCompanyId } = useCompanySelector("can_sell");
  const [reserves, setReserves] = useState<ReserveCommitment[]>([]);
  const [obligations, setObligations] = useState<PrimaryObligation[]>([]);
  const [commercialTerms, setCommercialTerms] = useState<Record<string,CommercialTerms>>({});
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);

  async function reload() {
    const token = getToken(); if (!token || !companyId) return;
    const [r, o] = await Promise.all([marketplace.getReserveInvitations(token, companyId), marketplace.getPrimaryObligations(token, companyId)]);
    setReserves(r); setObligations(o);
  }
  useEffect(() => { if (companyId) void reload().catch((err: unknown) => setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить резерв.")); }, [companyId]);

  async function decide(item: ReserveCommitment, decision: "approved" | "rejected") {
    const token = getToken(); if (!token || !companyId) return;
    const ask = (label: string, value: string | number | null) => window.prompt(label, value === null ? "" : String(value));
    const capacity = decision === "approved" ? ask("Подтверждённая мощность, ед.:", item.proposed_capacity_units) : null;
    const moq = decision === "approved" ? ask("минимальный заказ, ед.:", item.proposed_moq_units) : null;
    const price = decision === "approved" ? ask("Цена за единицу, ₽:", item.proposed_unit_price_rub) : null;
    const terms = commercialTerms[item.id]??emptyCommercialTerms;
    const delivery = ["included","self_pickup"].includes(terms.delivery_method) ? "0" : decision === "approved" ? ask("Логистика, ₽:", item.proposed_delivery_cost_rub) : null;
    const lead = decision === "approved" ? ask("Срок, дней:", item.proposed_lead_time_days) : null;
    const heldUntil = decision === "approved" ? window.prompt("Удерживать мощность до (ГГГГ-ММ-ДД):") : null;
    const switchover = decision === "approved" ? window.prompt("Переключение за, дней (пусто — не указано):", "") : null;
    if (decision === "approved" && [capacity, moq, price, delivery, lead, heldUntil].some((value) => !value)) return;
    const proposed = decision === "approved" ? {
      company_id: companyId, decision,
      commercial_terms: commercialTerms[item.id]??emptyCommercialTerms,
      capacity_units: Number(capacity), moq_units: Number(moq), unit_price_rub: String(price),
      delivery_cost_rub: String(delivery), lead_time_days: Number(lead),
      held_until: heldUntil,
      ...(switchover && switchover.trim() ? { switchover_days: Number(switchover) } : {}),
    } : { company_id: companyId, decision };
    if (!window.confirm(decision === "approved" ? "Подтвердить цену и удержание мощности?" : "Отклонить приглашение?")) return;
    setWorking(item.id);
    try { await marketplace.decideReserve(token, item.id, proposed); await reload(); }
    catch (err) { setError(err instanceof ApiError ? russianMessage(err.message) : "Решение не сохранено."); }
    finally { setWorking(null); }
  }

  async function report(item: PrimaryObligation) {
    const token = getToken(); if (!token || !companyId) return;
    const reason = window.prompt("Опишите производственный сбой:"); if (!reason) return;
    if (!window.confirm("Сообщить о фактическом сбое и запустить перепланирование?")) return;
    setWorking(item.plan_id);
    try { await marketplace.reportFailure(token, item.plan_id, companyId, reason); await reload(); }
    catch (err) { setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось сообщить о сбое."); }
    finally { setWorking(null); }
  }

  if (loading) return <p className="hint">Загрузка...</p>;
  if (meError || available.length === 0) return <div className="alert alert-error">{meError ?? "Нет компании с правом продажи."}</div>;
  return <div>
    <div className="company-row"><div><h1 className="page-title">Резерв и сбои</h1><p className="subtitle">Обязательства возникают только после вашего подтверждения</p></div><Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link></div>
    {available.length > 1 && <div className="field"><label>Компания</label><select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{available.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></div>}
    {error && <div className="alert alert-error">{error}</div>}
    <section className="card"><h2>Приглашения в резерв</h2>{reserves.length === 0 ? <p className="hint">Приглашений нет.</p> : reserves.map((item) => <article className="card" key={item.id}><CommercialTermsFields value={commercialTerms[item.id]??emptyCommercialTerms} onChange={value=>setCommercialTerms(current=>({...current,[item.id]:value}))} disabled={working === item.id} /><strong>{item.reserve_tier === "cold" ? "Холодный" : item.reserve_tier === "hot" ? "Горячий" : "Тёплый"} резерв · {russianLabel(item.confirmation_status, "Ожидает решения")}</strong><p>{formatUnits(item.proposed_capacity_units ?? 0)} · {formatRub(item.proposed_unit_price_rub, 12)}</p><div className="actions"><button className="btn btn-success btn-sm" disabled={working === item.id} onClick={() => void decide(item, "approved")}>Подтвердить условия</button><button className="btn btn-secondary btn-sm" disabled={working === item.id} onClick={() => void decide(item, "rejected")}>Отклонить</button></div></article>)}</section>
    <section className="card"><h2>Основные обязательства</h2>{obligations.length === 0 ? <p className="hint">Активных обязательств нет.</p> : obligations.map((item) => <article className="card" key={item.plan_id}><strong>План #{item.plan_id.slice(0, 8)}</strong><p>{formatUnits(item.allocation.units)} · {formatRub(item.allocation.total_cost_rub)} · {russianLabel(item.plan_status, "Статус уточняется")}</p><button className="btn btn-danger btn-sm" disabled={working === item.plan_id} onClick={() => void report(item)}>Сообщить о сбое</button></article>)}</section>
  </div>;
}

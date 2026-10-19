"use client";

import { formatDateTime } from "../lib/dates";

import { russianMessage } from "../lib/russianMessages";
import { FormEvent, useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import { DealExecution, ExecutionKind, formatRub, marketplace } from "../lib/marketplace";

const labels: Record<ExecutionKind, string> = { shipment: "Отгрузка", acceptance: "Приёмка", return: "Возврат", cancellation: "Отмена остатка" };
const states: Record<string, string> = { approved: "Возврат согласован, ожидается получение продавцом", pending: "Ожидает второй стороны", confirmed: "Подтверждено", rejected: "Отклонено" };
const rub = (value: string | number | null | undefined) => value == null ? "Нет данных" : formatRub(value);

export default function DealExecutionPanel({ dealId, companyId, isBuyer, canManage, executionControls = true }: { dealId: string; companyId: string; isBuyer: boolean; canManage: boolean; executionControls?: boolean }) {
  const [data, setData] = useState<DealExecution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<ExecutionKind>(isBuyer ? "acceptance" : "shipment");
  const [units, setUnits] = useState(""); const [note, setNote] = useState(""); const [approved, setApproved] = useState(false);
  const [unitCost, setUnitCost] = useState(""); const [expenses, setExpenses] = useState(""); const [costNote, setCostNote] = useState(""); const [taxBasis, setTaxBasis] = useState("unknown"); const [costApproved, setCostApproved] = useState(false);
  const taxLabels: Record<string, string> = { includes_vat: "цена с НДС", no_vat: "без НДС", unknown: "база не подтверждена" };
  const request = useRef<{ payload: string; key: string } | null>(null);
  const generation = useRef(0);
  async function reload() {
    const token = getToken(); if (!token) return;
    const current = ++generation.current;
    const value = await marketplace.getExecution(token, dealId, companyId);
    if (current !== generation.current) return;
    setData(value); setUnitCost(value.unit_cost_rub == null ? "" : String(value.unit_cost_rub));
    setExpenses(value.financials.attributable_expenses_rub == null ? "" : String(value.financials.attributable_expenses_rub));
    setCostNote(value.cost_note ?? ""); setTaxBasis(value.cost_tax_basis ?? "unknown");
  }
  useEffect(() => { void reload().catch((e: Error) => setError(e.message)); return () => { generation.current++; }; }, [dealId, companyId]);
  async function perform(action: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(true); setError(null); setNotice("");
    try { await action(); setNotice(success); await reload(); }
    catch (e) { setError(e instanceof Error ? russianMessage(e.message) : "Операция не выполнена. Повторите запрос."); }
    finally { setBusy(false); }
  }
  function submit(event: FormEvent) {
    event.preventDefault(); const token = getToken(); if (!token || !approved) return;
    const payload = { company_id: companyId, kind, units: Number(units), note: note.trim() };
    const fingerprint = JSON.stringify(payload);
    if (request.current?.payload !== fingerprint) request.current = { payload: fingerprint, key: crypto.randomUUID() };
    const key = request.current.key;
    void perform(async () => { await marketplace.recordExecution(token, dealId, { ...payload, idempotency_key: key }); request.current = null; setUnits(""); setNote(""); setApproved(false); }, kind === "acceptance" ? "Приёмка записана." : kind === "shipment" ? "Отгрузка записана." : "Запрос передан второй стороне.");
  }
  function saveCosts(event: FormEvent) {
    event.preventDefault(); const token = getToken(); if (!token || !data || !costApproved) return;
    void perform(async () => { await marketplace.saveDealCosts(token, dealId, { company_id: companyId, expected_revision: data.cost_revision ?? 0, unit_cost_rub: unitCost === "" ? null : unitCost, attributable_expenses_rub: expenses === "" ? null : expenses, tax_basis: taxBasis, note: costNote.trim() }); setCostApproved(false); }, "Затраты сохранены. Отчёт пересчитан.");
  }
  const max = kind === "return" ? data?.net_units : kind === "shipment" ? data?.unshipped_units : data?.open_units;
  return <section className="card" aria-busy={busy}>
    <h2>Исполнение и расчёты</h2>
    {error && <div className="alert alert-error" role="alert">{error}<button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void perform(reload, "Данные обновлены.")}>Обновить данные</button></div>}
    {notice && <p className="alert alert-success" role="status">{notice}</p>}
    {!data ? <p role="status">Загрузка исполнения…</p> : <>
      <dl className="stats-grid"><div><dt>Заказано</dt><dd>{data.ordered_units}</dd></div><div><dt>Отгружено</dt><dd>{data.shipped_units ?? "Нет данных"}</dd></div><div><dt>Принято</dt><dd>{data.accepted_units}</dd></div><div><dt>Возвращено</dt><dd>{data.returned_units}</dd></div><div><dt>Отменено</dt><dd>{data.cancelled_units}</dd></div><div><dt>Ожидается</dt><dd>{data.open_units}</dd></div></dl>
      <p>Цена товара за единицу: <b>{rub(data.financials.unit_price_rub)}</b>. Стоимость принятых товаров за вычетом возвратов: <b>{rub(data.financials.net_goods_revenue_rub)}</b>.</p>
      <p className="hint">Количество — в единицах этого заказа. Приёмку оформляет покупатель после отгрузки. Возврат и отмена остатка вступают в силу после подтверждения второй стороной. Возврат не увеличивает ожидаемую поставку.</p>
      {canManage && executionControls && <form className="form-grid" onSubmit={submit}>
        <div className="field"><label htmlFor="execution-kind">Операция</label><select id="execution-kind" value={kind} onChange={e => { setKind(e.target.value as ExecutionKind); setApproved(false); }}>{isBuyer && <><option value="acceptance">Подтвердить приёмку</option><option value="return">Запросить возврат</option></>}{!isBuyer && <option value="shipment">Подтвердить отгрузку части заказа</option>}<option value="cancellation">Запросить отмену остатка</option></select></div>
        <div className="field"><label htmlFor="execution-units">Количество (доступно {max})</label><input id="execution-units" required type="number" min="1" max={max} step="1" value={units} onChange={e => { setUnits(e.target.value); setApproved(false); }} /></div>
        <div className="field"><label htmlFor="execution-note">Основание или номер акта</label><textarea id="execution-note" required minLength={3} maxLength={1000} value={note} onChange={e => { setNote(e.target.value); setApproved(false); }} /></div>
        <label><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} required /> Подтверждаю вид операции и количество</label>
        <button className="btn btn-primary" disabled={busy || !approved || !max}>{busy ? "Сохранение…" : kind === "acceptance" ? "Записать приёмку" : kind === "shipment" ? "Записать отгрузку" : "Отправить запрос"}</button>
      </form>}
      <h3>История операций</h3>
      {!data.events.length ? <p className="hint">Операций пока нет. Заказ ещё не считается продажей.</p> : <ul>{data.events.map(item => <li key={item.id}><b>{labels[item.kind]}: {item.units}</b> · {states[item.status]}<br /><small>{formatDateTime(item.created_at)}</small><p>{item.note}</p>{executionControls && canManage && item.status === "pending" && item.actor_company_id !== companyId && <div className="company-row"><button className="btn btn-primary" disabled={busy} onClick={() => { const token = getToken(); if (token) void perform(() => marketplace.decideExecution(token, dealId, item.id, companyId, true), "Операция подтверждена."); }}>Подтвердить {item.units} ед.</button><button className="btn btn-secondary" disabled={busy} onClick={() => { const token = getToken(); if (token) void perform(() => marketplace.decideExecution(token, dealId, item.id, companyId, false), "Запрос отклонён."); }}>Отклонить запрос</button></div>}</li>)}</ul>}
      {!isBuyer && <details><summary>Себестоимость и прибыль — только для вашей компании</summary><p>Валовая прибыль: <b>{rub(data.financials.gross_profit_rub)}</b>. После указанных затрат: <b>{rub(data.financials.contribution_rub)}</b>.</p><p className="hint">Расчёт по указанным вами затратам, без подтверждения платежей. Пустое поле означает «неизвестно»; указывайте 0 только при подтверждённом отсутствии затрат. Прочие затраты — общая сумма по этому заказу, включая расходы на возвраты. Это не чистая бухгалтерская прибыль.</p><p className="hint">Налоговая база расчёта: <b>{taxLabels[data.cost_tax_basis ?? "unknown"] ?? data.cost_tax_basis}</b>{(data.cost_tax_basis ?? "unknown") === "unknown" ? " — прибыль не рассчитывается." : "."}{data.cost_updated_at ? ` Действует с ${formatDateTime(data.cost_updated_at)}.` : ""}</p>{data.financials.profit_missing_reason && <p>{data.financials.profit_missing_reason}</p>}{data.cost_history && <details><summary>Версии затрат</summary>{data.cost_history.map(c=><p key={c.revision}>Версия {c.revision} · {rub(c.unit_cost_rub)} за единицу · {rub(c.attributable_expenses_rub)} прочих затрат · {taxLabels[c.tax_basis] || "База неизвестна"} · с {formatDateTime(c.effective_from)} · {c.source}{c.legacy_history_unknown ? " · Более ранняя история неизвестна" : ""}</p>)}</details>}{canManage && <form className="form-grid" onSubmit={saveCosts}><div className="field"><label htmlFor="unit-cost">Себестоимость единицы, ₽</label><input id="unit-cost" type="number" min="0" step="0.01" value={unitCost} onChange={e => { setUnitCost(e.target.value); setCostApproved(false); }} /></div><div className="field"><label htmlFor="order-expenses">Прочие затраты заказа, ₽</label><input id="order-expenses" type="number" min="0" step="0.01" value={expenses} onChange={e => { setExpenses(e.target.value); setCostApproved(false); }} /></div><div className="field"><label htmlFor="tax-basis">Налоговая база затрат</label><select id="tax-basis" value={taxBasis} onChange={e => { setTaxBasis(e.target.value); setCostApproved(false); }}><option value="unknown">Не подтверждена</option><option value="includes_vat">Цена с НДС</option><option value="no_vat">Без НДС</option></select></div><div className="field"><label htmlFor="cost-note">Источник расчёта затрат</label><textarea id="cost-note" minLength={3} maxLength={1000} required value={costNote} onChange={e => { setCostNote(e.target.value); setCostApproved(false); }} /></div><label><input type="checkbox" checked={costApproved} required onChange={e => setCostApproved(e.target.checked)} /> Подтверждаю затраты для расчёта</label><button className="btn btn-primary" disabled={busy || !costApproved}>Сохранить затраты</button></form>}</details>}
    </>}
  </section>;
}

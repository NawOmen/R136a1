"use client";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { getToken } from "../lib/api";
import { russianMessage } from "../lib/russianMessages";
import { supplierWorkflow as api, SUPPLIER_STATUS, updateValues, type SupplierCandidate, type SupplierRequest, type SupplierStatus } from "../lib/supplierWorkflow";
import SupplierConversation from "./SupplierConversation";

const columns: SupplierStatus[] = ["sent", "replied", "selected"];
export default function SupplierBoard({ needId, companyId, needRevision, canManage, initialRequestId = "" }: { needId: string; companyId: string; needRevision: number; canManage: boolean; initialRequestId?: string }) {
  const [rows, setRows] = useState<SupplierRequest[]>([]), [candidates, setCandidates] = useState<SupplierCandidate[]>([]);
  const [supplierId, setSupplierId] = useState(""), [selectedId, setSelectedId] = useState(""), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [dragStatus, setDragStatus] = useState<SupplierStatus | null>(null);
  const generation = useRef(0);
  async function reload() {
    const token = getToken(); if (!token) return;
    const current = ++generation.current;
    const [items, suppliers] = await Promise.all([api.list(token, companyId, needId), api.candidates(token, needId, companyId)]);
    if (current !== generation.current) return;
    setRows(items); setCandidates(suppliers); setError("");
  }
  useEffect(() => {
    setLoading(true);
    setSelectedId(initialRequestId);
    void reload().catch(e => setError(russianMessage(e.message))).finally(() => setLoading(false));
    return () => { generation.current++; };
  }, [needId, companyId, needRevision, initialRequestId]);
  async function perform(action: (token: string) => Promise<void>) {
    const token = getToken(); if (!token || busy) return;
    setBusy(true); setError("");
    try { await action(token); }
    catch (e) { setError(e instanceof Error ? russianMessage(e.message) : "Не удалось обновить доску. Повторите попытку."); }
    finally { setBusy(false); }
  }
  function move(row: SupplierRequest, status: SupplierStatus) {
    if (!canManage || row.status === status) return;
    void perform(async token => { await api.update(token, row.id, updateValues(row, status)); await reload(); });
  }
  function drop(event: DragEvent, status: SupplierStatus) {
    event.preventDefault(); setDragStatus(null);
    const id = event.dataTransfer.getData("application/x-porukam-supplier-request");
    const row = rows.find(r => r.id === id && r.status !== "draft");
    if (row && canManage) move(row, status);
  }
  function card(row: SupplierRequest) {
    return <article key={row.id} className={`supplier-card${selectedId === row.id ? " supplier-card--active" : ""}`} draggable={canManage && !busy && row.status !== "draft"} onDragStart={e => { e.dataTransfer.setData("application/x-porukam-supplier-request", row.id); e.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => setDragStatus(null)}>
      <button type="button" className="supplier-card__open" aria-pressed={selectedId === row.id} onClick={() => setSelectedId(row.id)}><strong>{row.seller_name}</strong><span>Открыть чат</span>{row.need_revision !== needRevision && <small>Предыдущая версия требований</small>}</button>
      {row.status !== "draft" && canManage && <label className="supplier-card__status">Этап<select aria-label={`Этап: ${row.seller_name}`} value={row.status} disabled={busy} onChange={e => move(row, e.target.value as SupplierStatus)}>{columns.map(c => <option key={c} value={c}>{SUPPLIER_STATUS[c]}</option>)}</select></label>}
    </article>;
  }
  const selected = rows.find(r => r.id === selectedId);
  const drafts = rows.filter(r => r.status === "draft");
  return <section className="supplier-board" aria-label="Доска запросов и ответов">
    <header className="supplier-board__heading"><div><h2>Этапы запросов</h2><p className="hint">Запросите КП, сравните ответы и отметьте выбор. Заказ оформляется отдельно.</p></div><button type="button" className="btn btn-secondary btn-sm" disabled={busy || loading} onClick={() => void perform(async () => reload())}>Обновить доску</button></header>
    {error && <div className="alert alert-error" role="alert">{error}<button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void perform(async () => reload())}>Повторить</button></div>}
    {loading ? <p role="status">Загружаем поставщиков…</p> : <>
      {canManage && <form className="supplier-board__add" onSubmit={e => { e.preventDefault(); void perform(async token => { const row = await api.create(token, needId, companyId, supplierId, needRevision); await reload(); setSelectedId(row.id); }); }}><label>Получатель запроса<select aria-label="Получатель запроса" value={supplierId} onChange={e => setSupplierId(e.target.value)} required disabled={busy}><option value="">Выберите поставщика</option>{candidates.map(c => <option key={c.company_id} value={c.company_id}>{c.company_name}{c.relevant ? " · ваша категория" : ""}</option>)}</select></label><button className="btn btn-primary" disabled={busy || !supplierId}>Подготовить запрос</button></form>}
      {canManage && !candidates.length && <p className="hint">Проверенных поставщиков пока нет. Вернитесь к доске позже.</p>}
      {!!drafts.length && <details className="supplier-drafts" open><summary>Черновики запросов ({drafts.length})</summary><div>{drafts.map(card)}</div></details>}
      <div className="supplier-board__columns">{columns.map(status => <section key={status} className={`supplier-lane${dragStatus === status ? " supplier-lane--over" : ""}`} aria-label={SUPPLIER_STATUS[status]} onDragOver={e => { if (canManage && !busy) { e.preventDefault(); setDragStatus(status); } }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragStatus(null); }} onDrop={e => drop(e, status)}><h3>{SUPPLIER_STATUS[status]} <span>{rows.filter(r => r.status === status).length}</span></h3>{rows.filter(r => r.status === status).map(card)}{!rows.some(r => r.status === status) && <p className="hint">Пока пусто</p>}</section>)}</div>
      {selected ? <SupplierConversation key={`${selected.id}:${companyId}`} row={selected} companyId={companyId} canManage={canManage} onChanged={reload} /> : initialRequestId ? <p role="alert">Запрос не найден или недоступен этой компании.</p> : !!rows.length && <p className="hint">Откройте поставщика, чтобы перейти в чат.</p>}
    </>}
  </section>;
}

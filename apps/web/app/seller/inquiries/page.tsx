"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import SupplierConversation from "../../components/SupplierConversation";
import { getToken } from "../../lib/api";
import { useCompanySelector } from "../../lib/useMe";
import { supplierWorkflow, SUPPLIER_STATUS, type SupplierRequest } from "../../lib/supplierWorkflow";
import { russianMessage } from "../../lib/russianMessages";

export default function SupplierInquiries() {
  const me = useCompanySelector("can_sell");
  const [rows, setRows] = useState<SupplierRequest[]>([]), [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const companyRef = useRef(me.companyId);
  companyRef.current = me.companyId;
  async function reload() {
    const token = getToken(); if (!token || !me.companyId) return;
    const company = me.companyId;
    const items = await supplierWorkflow.list(token, company, undefined, "seller");
    if (company !== companyRef.current) return;
    setRows(items); setSelectedId(id => items.some(r => r.id === id) ? id : items[0]?.id ?? "");
  }
  useEffect(() => {
    let alive = true;
    setRows([]); setSelectedId(""); setLoading(true); setError("");
    const token = getToken();
    if (!token || !me.companyId) { if (!me.loading) setLoading(false); return; }
    supplierWorkflow.list(token, me.companyId, undefined, "seller").then(items => { if (alive) { setRows(items); setSelectedId(items[0]?.id ?? ""); } }).catch(e => { if (alive) setError(russianMessage(e.message)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [me.companyId, me.loading]);
  const selected = rows.find(r => r.id === selectedId);
  return <div><header className="company-row"><h1>Переписка с покупателями</h1><Link href="/seller/requests" className="btn btn-secondary">Запросы покупателей</Link></header>{me.error && <p role="alert" className="alert alert-error">{me.error}</p>}{error && <p role="alert" className="alert alert-error">{error}<button className="btn btn-secondary" onClick={() => void reload().then(() => setError("")).catch(e => setError(russianMessage(e.message)))}>Повторить</button></p>}
    {me.available.length > 1 && <label>Компания<select value={me.companyId} onChange={e => me.setCompanyId(e.target.value)}>{me.available.map(c => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></label>}
    {loading ? <p role="status">Загружаем запросы…</p> : !me.companyId ? <p className="hint">Нужна компания с правом продажи.</p> : !rows.length && !error ? <section className="card"><h2>Запросов пока нет</h2><p className="hint">Здесь появятся сообщения покупателей, которые выбрали вашу компанию.</p></section> : <div className="supplier-inbox"><aside aria-label="Запросы покупателей">{rows.map(row => <button className="supplier-inbox__item" key={row.id} aria-pressed={row.id === selectedId} onClick={() => setSelectedId(row.id)}><b>{row.buyer_name}</b><span>{row.specification.category}</span><small>{SUPPLIER_STATUS[row.status]}</small></button>)}</aside>{selected && <SupplierConversation key={`${selected.id}:${me.companyId}`} row={selected} companyId={me.companyId} canManage={!!me.company?.membership?.is_admin} onChanged={reload} />}</div>}
  </div>;
}

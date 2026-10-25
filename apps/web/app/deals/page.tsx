"use client";
import Link from "next/link";

import { useEffect, useState } from "react";
import CommercialEstimate from "../components/CommercialEstimate";
import DealExecutionPanel from "../components/DealExecutionPanel";
import DealFulfillmentPanel from "../components/DealFulfillmentPanel";
import { api, Company, getToken } from "../lib/api";
import { Deal, formatRub, formatUnits, marketplace } from "../lib/marketplace";


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

  return <div><div className="company-row"><h1>Сделки и сообщения</h1><Link href="/dashboard" className="btn btn-secondary">В личный кабинет</Link></div><p className="subtitle">Переписка, организация получения и контрольные точки</p>
    {error && <div className="alert alert-error">{error} <button type="button" className="btn btn-secondary btn-sm" disabled={loading} onClick={() => setRetry(n => n + 1)}>Повторить загрузку</button></div>}
    <div className="deal-layout"><aside className="card"><h2>Мои сделки</h2>
      {loading ? <p className="hint" role="status">Загружаем сделки…</p> : deals.length === 0 ? !error && <p className="hint">Сделок пока нет.</p> : deals.map(deal => <button type="button" className="deal-button" aria-pressed={selected?.id === deal.id} data-deal-id={deal.id} key={deal.id} onClick={() => { setSelected(deal); setActingCompanyId(""); }}>{formatUnits(deal.units)} · {formatRub(deal.total_price_rub)}</button>)}
    </aside><div>{selected && companyId ? <DealWorkspace key={`${selected.id}:${companyId}`} selected={selected} companyId={companyId} partyCompanies={partyCompanies} onCompanyChange={setActingCompanyId} /> : !loading && !error && <section className="card"><h2>Переписка</h2><p className="hint">Выберите сделку.</p></section>}</div></div>
  </div>;
}

function DealWorkspace({ selected, companyId, partyCompanies, onCompanyChange }: {
  selected: Deal; companyId: string; partyCompanies: Company[]; onCompanyChange: (id: string) => void;
}) {
  const [revision, setRevision] = useState(0);
  const isBuyer = companyId === selected.buyer_company_id;
  const canManage = partyCompanies.find(c => c.id === companyId)?.membership?.is_admin === true;
  return <div>
    <section className="card"><h2>Заказ: исполнение и получение</h2>{partyCompanies.length > 1 && <label>Компания в сделке<select aria-label="Компания в сделке" value={companyId} onChange={e => onCompanyChange(e.target.value)}>{partyCompanies.map(company => <option key={company.id} value={company.id}>{company.display_name}</option>)}</select></label>}</section>
    <details><summary>Исходная смета при заключении сделки</summary><CommercialEstimate value={selected.commercial_snapshot?.estimate} /></details>
    <DealFulfillmentPanel dealId={selected.id} companyId={companyId} isBuyer={isBuyer} canManage={canManage} onRevision={setRevision} />
    <DealExecutionPanel key={`${selected.id}:${companyId}:${revision}`} dealId={selected.id} companyId={companyId} isBuyer={isBuyer} canManage={canManage} executionControls={false} />
  </div>;
}

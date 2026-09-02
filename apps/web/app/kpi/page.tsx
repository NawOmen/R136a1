"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { marketplace, TrustKpi } from "../lib/marketplace";
import { useMe } from "../lib/useMe";

function rub(value: number) { return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(value); }

export default function KpiPage() {
  const { companies, user } = useMe();
  const [companyId, setCompanyId] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [kpi, setKpi] = useState<TrustKpi | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user && !initialized) {
      setCompanyId(user.is_marketplace_admin ? "" : (companies[0]?.id ?? ""));
      setInitialized(true);
    }
  }, [companies, initialized, user]);
  useEffect(() => {
    const token = getToken(); if (!initialized || !token || (!companyId && !user?.is_marketplace_admin)) return;
    marketplace.getKpi(token, companyId || undefined).then(setKpi).catch(() => setError("Не удалось рассчитать KPI."));
  }, [companyId, initialized, user]);

  return <div><div className="company-row"><h1 className="page-title">Проверяемые KPI</h1><Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link></div>
    <p className="subtitle">Показатели рассчитываются из неизменяемого журнала событий.</p>
    <div className="field"><label htmlFor="kpi-company">Компания</label><select id="kpi-company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{user?.is_marketplace_admin && <option value="">Весь маркетплейс</option>}{companies.map((company) => <option key={company.id} value={company.id}>{company.display_name}</option>)}</select></div>
    {error && <div className="alert alert-error">{error}</div>}
    {kpi && <><div className="form-grid"><div className="card"><h2>Покупатель</h2><p>Созданная ценность: {rub(kpi.buyer.created_value_rub ?? 0)}</p><p>Подтверждений: {kpi.buyer.human_approvals ?? 0}</p></div><div className="card"><h2>Производитель</h2><p>Созданная ценность: {rub(kpi.seller.created_value_rub ?? 0)}</p></div><div className="card"><h2>Маркетплейс</h2><p>GMV: {rub(kpi.marketplace.gmv_rub ?? 0)}</p><p>Событий: {kpi.generated_from_events}</p></div></div><p className="hint">{kpi.baseline_note}</p></>}
  </div>;
}

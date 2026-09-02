"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import { formatRub, formatUnits, marketplace, SellerAnalytics } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

export default function SellerAnalyticsPage() {
  const {loading, companyId, available, setCompanyId} = useCompanySelector("can_sell");
  const [data, setData] = useState<SellerAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const token = getToken(); if (!token || !companyId) return; marketplace.getSellerAnalytics(token, companyId).then(setData).catch((e: Error) => setError(e.message)); }, [companyId]);
  if (loading) return <p>Загрузка...</p>;
  return <div><div className="company-row"><div><h1>Продажи и статистика</h1><p className="subtitle">Режим «Продаю»</p></div><Link className="btn btn-secondary" href="/dashboard">В кабинет</Link></div>
    {available.length > 1 && <select value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{available.map((c) => <option value={c.id} key={c.id}>{c.display_name}</option>)}</select>}
    {error && <div className="alert alert-error">{error}</div>}{data && <div className="stats-grid"><article><b>{data.products_published} / {data.products_total}</b><span>товаров опубликовано</span></article><article><b>{data.deals_total}</b><span>сделок</span></article><article><b>{formatUnits(data.sold_units)}</b><span>продано</span></article><article><b>{formatRub(data.revenue_rub)}</b><span>оборот</span></article><article><b>{data.capacity_utilization_pct}%</b><span>загрузка мощности</span></article></div>}
    <section className="card"><h2>Связь с покупателем</h2><p>Переписка открывается внутри конкретной сделки и доступна только компаниям-участникам. Если сделок ещё нет, раздел останется пустым.</p></section>
  </div>;
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { CommercialReport, formatRub, marketplace } from "../lib/marketplace";
import { useCompanySelector } from "../lib/useMe";

const amount = (value: number | null | undefined) => value == null ? "Нет данных" : formatRub(Number(value));
const statuses: Record<string, string> = { created: "Оформлен", in_production: "Производство", shipped: "Отгружен", delivered: "Доставлен", partially_accepted: "Частичная приёмка", fulfilled: "Исполнен", cancelled: "Отменён", returned: "Возвращён" };

function csvCell(value: unknown): string {
  let text = value == null ? "Нет данных" : String(value);
  if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadReport(report: CommercialReport) {
  const header = ["Тип заказа", "Заказ", "Категория", "Единица измерения", "Создан (UTC)", "Статус", "Заказано", "Принято", "Возвращено", "Отменено", "Ожидается", "Цена за единицу, ₽", "Сумма заказа, ₽", "Товары после возвратов, ₽"];
  if (report.role === "seller") header.push("Себестоимость принятых товаров, ₽", "Валовая прибыль, ₽", "Прочие затраты, ₽", "Результат после затрат, ₽");
  const rows: unknown[][] = report.orders.map(row => {
    const values: unknown[] = ["Прямой", row.deal_id, row.category, row.unit, row.created_at, statuses[row.status] ?? row.status, row.ordered_units, row.accepted_units, row.returned_units, row.cancelled_units, row.open_units, row.unit_price_rub, row.ordered_value_rub, row.net_goods_revenue_rub];
    if (report.role === "seller") values.push(row.cost_of_goods_rub, row.gross_profit_rub, row.attributable_expenses_rub, row.contribution_rub);
    return values;
  });
  for (const row of report.group_orders) {
    const values: unknown[] = ["Групповой", row.order_id, row.category, row.unit, row.created_at, statuses[row.status] ?? row.status, row.units,
      null, null, null, null, null, row.contract_value_rub, null];
    if (report.role === "seller") values.push(null, null, null, null);
    rows.push(values);
  }
  const blob = new Blob(["\ufeff", [header, ...rows].map(row => row.map(csvCell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = "porukam-orders.csv"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function CommercialAnalytics({ role }: { role: "buyer" | "seller" }) {
  const { loading, companyId, available, setCompanyId, error: accountError } = useCompanySelector(role === "seller" ? "can_sell" : "can_buy");
  const [report, setReport] = useState<CommercialReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [start, setStart] = useState(""); const [end, setEnd] = useState(""); const [category, setCategory] = useState("");
  const [filters, setFilters] = useState<{ start?: string; end?: string; category?: string }>({});
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setReport(null); setError(null);
    const token = getToken(); if (!token || !companyId) return;
    setPending(true);
    marketplace.getCommercialReport(token, companyId, role, filters).then(value => { if (active) setReport(value); })
      .catch((e: Error) => { if (active) setError(e.message); }).finally(() => { if (active) setPending(false); });
    return () => { active = false; };
  }, [companyId, role, filters, refresh]);
  const visible = report?.company_id === companyId ? report : null;
  if (loading) return <p role="status">Загрузка аккаунта…</p>;
  return <div>
    <div className="company-row"><div><h1>{role === "seller" ? "Продажи и статистика" : "Закупки и статистика"}</h1><p className="subtitle">Заказы, исполнение и подтверждённые результаты</p></div><Link className="btn btn-secondary" href="/dashboard">В кабинет</Link></div>
    {(accountError || error) && <div className="alert alert-error" role="alert">{accountError || error}<button type="button" className="btn btn-secondary" onClick={() => setRefresh(n => n + 1)}>Повторить загрузку</button></div>}
    {available.length === 0 ? <p className="card">Нет компании с правом {role === "seller" ? "продажи" : "покупки"}. Добавьте компанию в кабинете.</p> : <>
      <div className="field"><label htmlFor="report-company">Компания</label><select id="report-company" value={companyId} onChange={e => setCompanyId(e.target.value)}>{available.map(c => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></div>
      <form className="card form-grid" onSubmit={e => { e.preventDefault(); setFilters({ start, end, category: category.trim() }); }}>
        <div className="field"><label htmlFor="report-start">Заказы с</label><input id="report-start" type="date" value={start} max={end || undefined} onChange={e => setStart(e.target.value)} /></div>
        <div className="field"><label htmlFor="report-end">Заказы по</label><input id="report-end" type="date" value={end} min={start || undefined} onChange={e => setEnd(e.target.value)} /></div>
        <div className="field"><label htmlFor="report-category">Категория (точное название)</label><input id="report-category" value={category} onChange={e => setCategory(e.target.value)} placeholder="Все категории" /></div>
        <button className="btn btn-primary" disabled={pending}>Показать</button>
      </form>
      {pending && <p role="status">Загрузка отчёта…</p>}
      {visible && <>
        <div className="stats-grid">
          <article><b>{visible.orders_count}</b><span>прямых заказов</span></article>
          <article><b>{amount(visible.totals.ordered_value_rub)}</b><span>сумма заказов с доставкой</span></article>
          <article><b>{amount(visible.totals.net_goods_revenue_rub)}</b><span>{role === "seller" ? "выручка от принятых товаров" : "принятые товары"}, за вычетом возвратов</span></article>
          {role === "seller" && <><article><b>{amount(visible.totals.gross_profit_rub)}</b><span>валовая прибыль · затраты известны для {visible.totals.gross_profit_rub_known_orders} из {visible.orders_count} заказов</span></article><article><b>{amount(visible.totals.contribution_rub)}</b><span>результат после указанных затрат</span></article></>}
          <article><b>{visible.rejected_offers_count} / {visible.offers_count}</b><span>отклонено предложений</span></article>
        </div>
        <p className="hint">{visible.explanation}</p>
        <p className="hint">«Нет данных» означает, что сумма неизвестна. Количество указано в единицах конкретного заказа; объёмы разных товаров не складываются. Платёжные поступления и чистая прибыль не рассчитываются.</p>
        <section className="card"><div className="company-row"><h2>Подробности заказов</h2><button className="btn btn-secondary" type="button" disabled={!visible.orders.length && !visible.group_orders.length} onClick={() => downloadReport(visible)}>Скачать CSV</button></div>
          {!visible.orders.length ? <p>{visible.group_orders.length ? "Прямых заказов в выбранном периоде нет. Групповые обязательства показаны ниже." : "В выбранном периоде заказов нет. Измените фильтры или оформите первый заказ."}</p> : <div style={{ overflowX: "auto" }} tabIndex={0} aria-label="Таблица заказов, можно прокручивать по горизонтали"><table><thead><tr><th>Заказ / категория</th><th>Цена за единицу</th><th>Заказано</th><th>Принято</th><th>Возвращено</th><th>Отменено</th><th>Ожидается</th><th>Товары после возвратов</th>{role === "seller" && <><th>Валовая прибыль</th><th>После затрат</th></>}</tr></thead><tbody>{visible.orders.map(row => <tr key={row.deal_id}><td><Link href={`/deals?deal=${row.deal_id}`}>{row.deal_id.slice(0, 8)}</Link><br />{row.category} · {row.unit}<br /><small>{statuses[row.status] ?? row.status}</small></td><td>{amount(row.unit_price_rub)}</td><td>{row.ordered_units}</td><td>{row.accepted_units}</td><td>{row.returned_units}</td><td>{row.cancelled_units}</td><td>{row.open_units}</td><td>{amount(row.net_goods_revenue_rub)}</td>{role === "seller" && <><td>{amount(row.gross_profit_rub)}</td><td>{amount(row.contribution_rub)}</td></>}</tr>)}</tbody></table></div>}
        </section>
        <section className="card"><h2>Групповые обязательства: {visible.group_orders_count}</h2>
          <p className="hint">Суммы согласованных условий показаны отдельно от продаж и закупок с подтверждённой приёмкой. Исполнение и платежи по ним здесь не подтверждены.</p>
          {!visible.group_orders.length ? <p>В выбранном периоде групповых обязательств нет.</p> : <ul className="company-list">{visible.group_orders.map(row => <li className="company-item" key={row.order_id}><strong>{row.category} · {row.units} {row.unit} · {amount(row.contract_value_rub)}</strong><span className="company-meta">{new Date(row.created_at).toLocaleDateString("ru-RU")} · {statuses[row.status] ?? row.status} · группа {row.coalition_id.slice(0, 8)}</span></li>)}</ul>}
        </section>
      </>}
    </>}
  </div>;
}

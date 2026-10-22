"use client";
import { DateInput } from "./DateInput";
import { formatDate, formatDateTime, formatMonth } from "../lib/dates";

import { russianMessage } from "../lib/russianMessages";
import { russianLabel, displayValue } from "../lib/presentation";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import { russianUnit, CommercialReport, formatRub, marketplace } from "../lib/marketplace";
import { useCompanySelector } from "../lib/useMe";

const amount = (value: string | number | null | undefined) => value == null ? "Нет данных" : formatRub(value);
const statuses: Record<string, string> = { created: "Оформлен", in_production: "Производство", shipped: "Отгружен", delivered: "Доставлен", partially_shipped: "Частичная отгрузка", disputed: "Спор", partially_accepted: "Частичная приёмка", fulfilled: "Исполнен", cancelled: "Отменён", returned: "Возвращён" };
const DEAL_STATUSES = ["created", "in_production", "shipped", "delivered", "partially_shipped", "disputed", "partially_accepted", "fulfilled", "cancelled", "returned"];

async function downloadCsv(report: CommercialReport, companyId: string, role: "buyer" | "seller", filters: { start?: string; end?: string; category?: string; status?: string; counterparty?: string; product?: string; source?: string }, stillVisible: () => boolean) {
  const token = getToken(); if (!token) return;
  const blob = await marketplace.downloadCommercialCsv(token, companyId, role, filters, report.report_id);
  if (!stillVisible()) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url;
  const stamp = `${filters.start || "all"}_${filters.end || "all"}`;
  link.download = `porukam-${role}-${stamp}.csv`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function CommercialAnalytics({ role }: { role: "buyer" | "seller" }) {
  const { loading, companyId, available, setCompanyId, error: accountError } = useCompanySelector(role === "seller" ? "can_sell" : "can_buy");
  const [report, setReport] = useState<CommercialReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [start, setStart] = useState(""); const [end, setEnd] = useState(""); const [category, setCategory] = useState("");
  const [status, setStatus] = useState(""); const [counterparty, setCounterparty] = useState(""); const [product, setProduct] = useState("");
  const [source, setSource] = useState("all");
  const [filters, setFilters] = useState<{ start?: string; end?: string; category?: string; status?: string; counterparty?: string; product?: string; source?: string }>({});
  const [refresh, setRefresh] = useState(0);
  const scope = useRef(""); scope.current = `${companyId}:${role}:${report?.report_id || ""}:${JSON.stringify(filters)}`;
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
  async function handleDownload() {
    if (!visible) return;
    setDownloading(true); setError(null);
    const requestedScope = scope.current;
    try { await downloadCsv(visible, companyId, role, filters, () => scope.current === requestedScope); }
    catch (e) { if(scope.current === requestedScope) setError(e instanceof Error ? russianMessage(e.message) : "Не удалось выгрузить отчёт."); }
    finally { setDownloading(false); }
  }
  if (loading) return <p role="status">Загрузка аккаунта…</p>;
  return <div>
    <div className="company-row"><div><h1>{role === "seller" ? "Продажи и статистика" : "Закупки и статистика"}</h1><p className="subtitle">Заказы, исполнение и подтверждённые результаты</p></div><Link className="btn btn-secondary" href="/dashboard">В кабинет</Link></div>
    {(accountError || error) && <div className="alert alert-error" role="alert">{accountError || error}<button type="button" className="btn btn-secondary" onClick={() => setRefresh(n => n + 1)}>Повторить загрузку</button></div>}
    {available.length === 0 ? <p className="card">Нет компании с правом {role === "seller" ? "продажи" : "покупки"}. Добавьте компанию в кабинете.</p> : <>
      <div className="field"><label htmlFor="report-company">Компания</label><select id="report-company" value={companyId} onChange={e => setCompanyId(e.target.value)}>{available.map(c => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></div>
      <form className="card form-grid" onSubmit={e => { e.preventDefault(); setFilters({ start, end, category: category.trim(), status, counterparty: counterparty.trim(), product: product.trim(), source }); }}>
        <div className="field"><label htmlFor="report-start">Заказы с</label><DateInput id="report-start" value={start} max={end || undefined} onValueChange={e => setStart(e)} /></div>
        <div className="field"><label htmlFor="report-end">Заказы по</label><DateInput id="report-end" value={end} min={start || undefined} onValueChange={e => setEnd(e)} /></div>
        <div className="field"><label htmlFor="report-category">Категория (точное название)</label><input id="report-category" value={category} onChange={e => setCategory(e.target.value)} placeholder="Все категории" /></div>
        <div className="field"><label htmlFor="report-status">Статус заказа</label><select id="report-status" value={status} onChange={e => setStatus(e.target.value)}><option value="">Все статусы</option>{DEAL_STATUSES.map(s => <option key={s} value={s}>{statuses[s] ?? russianLabel(s, "Статус уточняется")}</option>)}</select></div>
        <div className="field"><label htmlFor="report-counterparty">Контрагент (часть названия)</label><input id="report-counterparty" value={counterparty} onChange={e => setCounterparty(e.target.value)} placeholder="Все контрагенты" /></div>
        <div className="field"><label htmlFor="report-product">Товар (часть названия)</label><input id="report-product" value={product} onChange={e => setProduct(e.target.value)} placeholder="Все товары" /></div>
        <div className="field"><label htmlFor="report-source">Источник заказа</label><select id="report-source" value={source} onChange={e => setSource(e.target.value)}><option value="all">Прямые и групповые</option><option value="direct">Только прямые</option><option value="group">Только групповые</option></select></div>
        <button className="btn btn-primary" disabled={pending}>Показать</button>
      </form>
      {pending && <p role="status">Загрузка отчёта…</p>}
      {visible && <>
        <div className="stats-grid">
          <article><b>{visible.orders_count}</b><span>прямых заказов</span></article>
          <article><b>{amount(visible.totals.ordered_value_rub)}</b><span>сумма заказов с доставкой</span></article>
          <article><b>{amount(visible.totals.net_goods_revenue_rub)}</b><span>{role === "seller" ? "выручка от принятых товаров" : "принятые товары"}, за вычетом возвратов</span></article>
          {role === "seller" && <><article><b>{amount(visible.totals.gross_profit_rub)}</b><span>валовая прибыль · затраты известны для {visible.totals.gross_profit_rub_known_orders} из {visible.orders_count} заказов</span></article><article><b>{amount(visible.totals.contribution_rub)}</b><span>результат после указанных затрат</span></article></>}
          <article><b>{visible.rejection_rate.rejected} / {visible.rejection_rate.known_outcomes}</b><span>отклонено с известным исходом{visible.rejection_rate.open ? ` · открыто ${visible.rejection_rate.open}` : ""}{visible.rejection_rate.stale ? ` · истекло ${visible.rejection_rate.stale}` : ""}</span></article>
          <article><b>{visible.rejection_rate.rate_pct == null ? "Нет данных" : `${visible.rejection_rate.rate_pct} %`}</b><span>доля отказов когорты предложений</span></article>
        </div>
        {visible.average_prices.length > 0 && <section className="card"><h2>Средние цены исполненного</h2><ul className="company-list">{visible.average_prices.map(row => <li key={row.cohort_key} className="company-row"><span>{row.product_name || "Сопоставимая спецификация"} · {russianUnit(row.unit)}</span><b>{amount(row.average_unit_price_rub)} / ед. · принято после возвратов {row.net_units}</b></li>)}</ul><p className="hint">Среднее — сумма после возвратов на оставшееся принятое количество одной замороженной спецификации и условий.</p></section>}
        {visible.monthly.length > 0 && <section className="card"><h2>Динамика по месяцам создания</h2><div style={{ overflowX: "auto" }} tabIndex={0} aria-label="Динамика заказов по месяцам"><table style={{minWidth:560}}><thead><tr><th>Месяц</th><th>Заказов</th><th>Принято, ₽</th><th>Принято, кол-во</th></tr></thead><tbody>{visible.monthly.map(row => <tr key={row.month}><td>{formatMonth(row.month)}</td><td>{row.orders_count}</td><td>{amount(row.accepted_value_rub)}<br /><small>Покрытие: {row.value_known_orders} из {row.orders_count}</small></td><td>{row.accepted_units == null ? "несопоставимые товары" : `${row.accepted_units} ${russianUnit(row.unit)}`}</td></tr>)}</tbody></table></div></section>}
        <section className="card"><h2>Надёжность исполнения</h2><p>{visible.reliability.on_time_share_pct == null ? "Не оценено" : `${visible.reliability.on_time_share_pct} % вовремя без отмен и возвратов`} · известные исходы: {visible.reliability.known_outcomes} из {visible.reliability.orders}. Минимум для оценки — 5.</p></section>
        {visible.historical_recalculated && <p role="status" className="alert">Исторический отчёт пересчитан с учётом более поздних событий или затрат. Выгрузка сохранит именно этот снимок.</p>}
        <section className="card"><h2>События выбранного периода</h2>{visible.period_events.length === 0 ? <p>Событий нет.</p> : <ul className="company-list">{visible.period_events.map(e => <li key={e.event_id}><Link href={`/deals?deal=${e.deal_id}`}>Заказ {e.deal_id.slice(0,8)}</Link> · {({acceptance:"Приёмка",return:"Возврат",cancellation:"Отмена",shipment:"Отгрузка"} as Record<string,string>)[e.kind] || "Операция"} · {e.units} {russianUnit(e.unit)} · {formatDateTime(e.occurred_at)} · {amount(e.goods_value_rub)}{e.source_acceptances.length>0 && <p>Исходная приёмка: {e.source_acceptances.map(s=>`${s.acceptance_event_id?.slice(0,8)||"Нет данных"} (${s.units})`).join(", ")}</p>}</li>)}</ul>}</section>
        <details className="workflow-details"><summary>Как считаются показатели</summary><p className="hint">{visible.explanation}</p></details>
        <p className="hint">Отчёт построен {formatDateTime(visible.built_at)}. «Нет данных» означает, что сумма неизвестна. Количество указано в единицах конкретного заказа; объёмы разных товаров не складываются. Платёжные поступления и чистая прибыль не рассчитываются.</p>
        <section className="card"><div className="company-row"><h2>Подробности заказов</h2><button className="btn btn-secondary" type="button" disabled={downloading || (!visible.orders.length && !visible.group_orders.length && !visible.period_events.length)} onClick={() => void handleDownload()}>{downloading ? "Готовим файл…" : "Скачать CSV"}</button></div>
          <p className="hint">Выгрузка строится сервером из тех же данных, фильтров и определений; права проверяются при каждом запросе.</p>
          {!visible.orders.length ? <p>{visible.group_orders.length ? "Прямых заказов в выбранном периоде нет. Групповые обязательства показаны ниже." : "В выбранном периоде заказов нет. Измените фильтры или оформите первый заказ."}</p> : <div style={{ overflowX: "auto" }} tabIndex={0} aria-label="Таблица заказов, можно прокручивать по горизонтали"><table style={{minWidth:1100}}><thead><tr><th>Заказ / категория</th><th>Цена за единицу</th><th>Заказано</th><th>Принято</th><th>Возвращено</th><th>Отменено</th><th>Ожидается</th><th>Товары после возвратов</th>{role === "seller" && <><th>Валовая прибыль</th><th>После затрат</th></>}</tr></thead><tbody>{visible.orders.map(row => <tr key={row.deal_id}><td><Link href={`/deals?deal=${row.deal_id}`}>{row.deal_id.slice(0, 8)}</Link><br />{row.category} · {russianUnit(row.unit)}<br /><small>{statuses[row.status] ?? "Статус не определён"}</small><details><summary>Смета и источники</summary><p>{row.product_name || "Историческое название неизвестно"} · {row.estimate_complete ? "Смета полная" : "Смета неполная"}</p><p>Скидка: {amount(row.discount_rub)} · Доставка: {amount(row.delivery_price_rub)}</p>{row.charge_lines.map((line,i)=><p key={i}>{line.title}: {amount(line.amount_rub)} · источник: {displayValue(line.source)}</p>)}{row.missing.map(m=><p key={m}>{m}</p>)}{role==="seller" && <><p>Затраты: версия {row.cost_revision ?? "Нет данных"} · {row.cost_tax_basis === "no_vat" ? "Без НДС" : row.cost_tax_basis === "includes_vat" ? "С НДС" : "Налоговая база неизвестна"}</p><p>{displayValue(row.cost_source)}</p><p>{row.profit_missing_reason}</p>{row.cost_history?.map(c=><p key={c.revision}>Версия {c.revision} · {amount(c.unit_cost_rub)} · с {formatDateTime(c.effective_from)} · {displayValue(c.source)}{c.legacy_history_unknown ? " · Более ранняя история неизвестна" : ""}</p>)}</>}</details></td><td>{amount(row.unit_price_rub)}</td><td>{row.ordered_units}</td><td>{row.accepted_units}</td><td>{row.returned_units}</td><td>{row.cancelled_units}</td><td>{row.open_units}</td><td>{amount(row.net_goods_revenue_rub)}</td>{role === "seller" && <><td>{amount(row.gross_profit_rub)}</td><td>{amount(row.contribution_rub)}</td></>}</tr>)}</tbody></table></div>}
        </section>
        <section className="card"><h2>Групповые обязательства: {visible.group_orders_count}</h2>
          <p className="hint">Согласованные суммы показаны отдельно от принятого товара. Исполнение и платежи по этим обязательствам не подтверждены.</p>
          {!visible.group_orders.length ? <p>В выбранном периоде групповых обязательств нет.</p> : <ul className="company-list">{visible.group_orders.map(row => <li className="company-item" key={row.order_id}><strong>{row.category} · {row.units} {russianUnit(row.unit)} · {amount(row.contract_value_rub)}</strong><span className="company-meta">{formatDate(row.created_at)} · {statuses[row.status] ?? "Статус не определён"} · группа {row.coalition_id.slice(0, 8)}</span></li>)}</ul>}
        </section>
      </>}
    </>}
  </div>;
}

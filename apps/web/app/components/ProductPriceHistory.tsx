"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { agents, PriceForecast } from "../lib/agents";
import { getToken } from "../lib/api";
import { formatDate } from "../lib/dates";
import { formatRub, marketplace, PriceIndexPoint } from "../lib/marketplace";
import { russianMessage } from "../lib/russianMessages";

export function ProductPriceHistory({ productId, category }: { productId: string; category: string }) {
  const [history, setHistory] = useState<PriceIndexPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [forecast, setForecast] = useState<PriceForecast | null>(null);
  const [forecastBusy, setForecastBusy] = useState(false);
  const [forecastError, setForecastError] = useState("");
  const [signIn, setSignIn] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    generation.current++;
    setHistory([]); setLoading(true); setError(false); setForecast(null); setForecastBusy(false); setForecastError(""); setSignIn(false);
    marketplace.getPriceIndex(category, productId).then(items => { if (active) setHistory(items); })
      .catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; generation.current++; };
  }, [productId, category, retry]);
  async function requestForecast() {
    const token = getToken();
    if (!token) { setSignIn(true); return; }
    const current = ++generation.current;
    setForecastBusy(true); setForecastError(""); setSignIn(false);
    try {
      const result = await agents.priceForecast(token, productId);
      if (current === generation.current) setForecast(result);
    } catch (reason) { if (current === generation.current) setForecastError(russianMessage(reason instanceof Error ? reason.message : "")); }
    finally { if (current === generation.current) setForecastBusy(false); }
  }
  const prices = history.map(point => Number(point.average_unit_price_rub));
  const min = Math.min(...prices), max = Math.max(...prices);
  const start = history.length ? Date.parse(history[0].date) : 0;
  const span = history.length ? Math.max(1, Date.parse(history.at(-1)!.date) - start) : 1;
  const line = history.map((point, i) => `${12 + (Date.parse(point.date) - start) / span * 576},${100 - (prices[i] - min) / (max - min || 1) * 72}`).join(" ");
  const rows = (points: PriceIndexPoint[]) => <div className="price-index">{points.map(point => <div key={point.date}><span>{formatDate(point.date)}</span><b>{formatRub(point.average_unit_price_rub)}</b></div>)}</div>;
  return <section className="card product-price-history"><h2>История и прогноз цены</h2><p className="hint">Опубликованные цены этого товара при тех же характеристиках и минимальной партии. Это не цены совершённых сделок.</p>
    {loading ? <p role="status">Загружаем историю цен…</p> : error ? <p className="alert alert-warning" role="alert">История цен временно недоступна. <button className="btn btn-secondary btn-sm" onClick={() => setRetry(value => value + 1)}>Повторить загрузку истории</button></p> : history.length ? <>
      {history.length > 1 && <svg className="price-history-chart" viewBox="0 0 600 120" role="img" aria-label="Изменение опубликованной цены. Точные цены и даты приведены ниже."><path d="M12 106H588" fill="none" stroke="var(--border)" /><polyline points={line} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" /></svg>}
      {rows(history.slice(-6))}{history.length > 6 && <details><summary>Вся история ({history.length} дат)</summary>{rows(history.slice(0, -6))}</details>}
    </> : <p className="hint">История появится после публикации и изменения цены. Пропущенные даты не заполняются вымышленными данными.</p>}
    <div className="price-forecast"><div className="company-row"><h3>Оценка на 30 дней</h3><button type="button" className="btn btn-secondary" disabled={forecastBusy || loading || error || history.length === 0} onClick={() => void requestForecast()}>{forecastBusy ? "Анализируем…" : forecast ? "Обновить прогноз с ИИ" : "Прогноз с ИИ"}</button></div>
      <p className="hint">Тренд считает программа, ИИ анализирует ограничения. Будущая цена зависит от решения продавца.</p>
      {forecastBusy && <p role="status">Изучаем историю товара…</p>}
      {signIn && <p><Link href="/login">Войдите</Link>, чтобы запросить ИИ-анализ.</p>}
      {forecastError && <p className="alert alert-error" role="alert">{forecastError}</p>}
      {forecast && <div aria-live="polite">{forecast.status === "ready" && <><p className="hint">{forecast.ai_status === "completed" ? "ИИ-анализ выполнен" : "Программная оценка"} · {forecast.observations} наблюдений · {formatDate(forecast.history_from)}–{formatDate(forecast.history_to)}</p><div className="forecast-points">{forecast.points.map(point => <div key={point.date}><span>{formatDate(point.date)}</span><strong>{formatRub(point.price_rub)}</strong></div>)}</div></>}{forecast.notes.map(note => <p className="hint" key={note}>{note}</p>)}</div>}
    </div>
  </section>;
}

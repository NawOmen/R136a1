"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { AgentScorecard, marketplace, TrustKpi } from "../lib/marketplace";
import { useMe } from "../lib/useMe";

function rub(value: number) { return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(value); }

export default function KpiPage() {
  const { companies, user } = useMe();
  const [companyId, setCompanyId] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [kpi, setKpi] = useState<TrustKpi | null>(null);
  const [scorecard, setScorecard] = useState<AgentScorecard | null>(null);
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
    // Оценка агентов: для компании — своя, для администратора — по всей площадке.
    const scorecardRequest = companyId
      ? marketplace.getAgentScorecard(token, companyId)
      : marketplace.getPlatformAgentScorecard(token);
    scorecardRequest.then(setScorecard).catch(() => setScorecard(null));
  }, [companyId, initialized, user]);

  return <div><div className="company-row"><h1 className="page-title">Проверяемые KPI</h1><Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link></div>
    <p className="subtitle">Показатели рассчитываются из неизменяемого журнала событий.</p>
    <div className="field"><label htmlFor="kpi-company">Компания</label><select id="kpi-company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{user?.is_marketplace_admin && <option value="">Весь маркетплейс</option>}{companies.map((company) => <option key={company.id} value={company.id}>{company.display_name}</option>)}</select></div>
    {error && <div className="alert alert-error">{error}</div>}
    {scorecard && (
      <section className="card">
        <h2>Оценка работы агентов</h2>
        <p className="hint">
          Показатели считаются из журналов за последние {scorecard.window_days} дней. Правки человека
          показывают, какие поля агент угадывает хуже всего; отсутствие данных не подменяется нулями.
        </p>
        <div className="form-grid">
          <div className="card">
            <h3>Черновики КП</h3>
            <p>Сформировано: {scorecard.offer_drafts_total}</p>
            <p>Отправлено после проверки: {scorecard.offer_drafts_used}</p>
            <p>Конверсия сценария: {scorecard.offer_draft_conversion_pct} %</p>
            <p>Среднее число правок человеком: {scorecard.average_changed_fields}</p>
            <p>Сделок из черновиков: {scorecard.deals_from_drafts} из {scorecard.deals_total}</p>
          </div>
          <div className="card">
            <h3>Контроль человека</h3>
            <p>Подтверждений человека: {scorecard.human_approvals}</p>
            <p>Заблокированных действий: {scorecard.blocked_actions}</p>
            <p>Проверок допуска: {scorecard.admission_checks}</p>
            <p>Остановлено на допуске: {scorecard.admission_blocked}</p>
            <p>Рекомендации: {scorecard.recommendations_converted} из {scorecard.recommendations_total} ({scorecard.recommendation_conversion_pct} %)</p>
          </div>
          <div className="card">
            <h3>Модель</h3>
            {scorecard.llm_metrics_available ? (
              <>
                <p>Запусков агентов: {scorecard.agent_runs_total}</p>
                <p>Отказов модели: {scorecard.agent_runs_failed}</p>
                <p>Локальный маршрут: {scorecard.agent_runs_local_route}; внешний: {scorecard.agent_runs_external_route}</p>
                <p>Средняя длительность: {scorecard.agent_average_duration_ms} мс</p>
                <p>Оценочная стоимость инференса: {rub(scorecard.agent_estimated_cost_rub)}</p>
              </>
            ) : (
              <p className="hint">Журнал вызовов LLM Gateway недоступен: метрики модели не рассчитаны.</p>
            )}
          </div>
        </div>
        {scorecard.notes.length > 0 && (
          <ul className="company-list">{scorecard.notes.map((note) => <li key={note}><span className="company-meta">{note}</span></li>)}</ul>
        )}
      </section>
    )}
    {kpi && <><div className="form-grid"><div className="card"><h2>Покупатель</h2><p>Созданная ценность: {rub(kpi.buyer.created_value_rub ?? 0)}</p><p>Подтверждений: {kpi.buyer.human_approvals ?? 0}</p></div><div className="card"><h2>Производитель</h2><p>Созданная ценность: {rub(kpi.seller.created_value_rub ?? 0)}</p></div><div className="card"><h2>Маркетплейс</h2><p>GMV: {rub(kpi.marketplace.gmv_rub ?? 0)}</p><p>Событий: {kpi.generated_from_events}</p></div></div><p className="hint">{kpi.baseline_note}</p></>}
  </div>;
}

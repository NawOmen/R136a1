"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { AgentScorecard, AuditEvent, AuditVerification, marketplace, TrustKpi } from "../lib/marketplace";
import { useMe } from "../lib/useMe";

function rub(value: number) { return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(value); }

export default function KpiPage() {
  const { companies, user } = useMe();
  const [companyId, setCompanyId] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [kpi, setKpi] = useState<TrustKpi | null>(null);
  const [scorecard, setScorecard] = useState<AgentScorecard | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user && !initialized) {
      setCompanyId(user.is_marketplace_admin ? "" : (companies[0]?.id ?? ""));
      setInitialized(true);
    }
  }, [companies, initialized, user]);
  useEffect(() => {
    const token = getToken(); if (!initialized || !token || (!companyId && !user?.is_marketplace_admin)) return;
    let active = true;
    setKpi(null); setScorecard(null); setError(null); setAuditEvents([]); setAuditError(null); setVerification(null);
    marketplace.getKpi(token, companyId || undefined).then((value) => { if (active) setKpi(value); }).catch(() => { if (active) setError("Не удалось рассчитать показатели."); });
    const scorecardRequest = companyId
      ? marketplace.getAgentScorecard(token, companyId)
      : marketplace.getPlatformAgentScorecard(token);
    scorecardRequest.then((value) => { if (active) setScorecard(value); }).catch(() => { if (active) setScorecard(null); });
    marketplace.getAuditEvents(token, companyId || undefined)
      .then((value) => { if (active) setAuditEvents(value); })
      .catch(() => { if (active) setAuditError("Не удалось загрузить журнал решений."); });
    if (user?.is_marketplace_admin) marketplace.verifyAudit(token)
      .then((value) => { if (active) setVerification(value); })
      .catch(() => { if (active) setAuditError("Не удалось проверить цепочку журнала."); });
    return () => { active = false; };
  }, [companyId, initialized, user]);

  return <div><div className="company-row"><h1 className="page-title">Проверяемые KPI</h1><Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link></div>
    <p className="subtitle">Показатели рассчитываются из записей операций и журнала событий.</p>
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
                <p>Смешанный маршрут: {scorecard.agent_runs_mixed_route}; по правилам: {scorecard.agent_runs_rules_route}; не определён: {scorecard.agent_runs_unknown_route}</p>
                <p>Средняя длительность: {scorecard.agent_average_duration_ms} мс</p>
                <p>Известные оценки затрат: {scorecard.agent_costed_runs ? rub(scorecard.agent_estimated_cost_rub) : "Нет данных"} ({scorecard.agent_costed_runs} из {scorecard.agent_runs_total} запусков)</p>
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
    {kpi && <><div className="form-grid"><div className="card"><h2>Покупатель</h2><p>Созданная ценность: {kpi.buyer.value_events ? rub(kpi.buyer.created_value_rub) : "Нет данных для сравнения"}</p><p>Подтверждений: {kpi.buyer.human_approvals ?? 0}</p></div><div className="card"><h2>Производитель</h2><p>Созданная ценность: {kpi.seller.value_events ? rub(kpi.seller.created_value_rub) : "Нет данных для сравнения"}</p></div><div className="card"><h2>Маркетплейс</h2><p>GMV: {rub(kpi.marketplace.gmv_rub ?? 0)}</p><p>Событий: {kpi.generated_from_events}</p></div></div><p className="hint">{kpi.baseline_note}</p></>}
    <section className="card"><h2>Журнал решений</h2>
      <p className="hint">Последние 50 событий выбранной компании. Запись показывает действие и его причину; история другой компании недоступна.</p>
      {verification && <p role="status">Проверка последовательности и хешей: {verification.valid ? `успешна, ${verification.checked_events} событий` : `ошибка на событии № ${verification.broken_sequence}`}. Это не защита от изменения базы администратором.</p>}
      {auditError && <div className="alert alert-error">{auditError}</div>}
      {!auditError && auditEvents.length === 0 ? <p className="hint">Событий пока нет.</p> : <ul className="company-list">{auditEvents.map((event) => <li key={event.id} className="company-item"><strong>№ {event.sequence} · {event.event_type}</strong><span className="company-meta">{new Date(event.created_at).toLocaleString("ru-RU")} · {event.entity_type}{event.entity_id ? ` · ${event.entity_id}` : ""}</span><p>{event.explanation}</p></li>)}</ul>}
    </section>
  </div>;
}

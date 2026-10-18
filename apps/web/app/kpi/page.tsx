"use client";
import { russianLabel } from "../lib/presentation";
import { formatRub } from "../lib/marketplace";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { AgentScorecard, AuditEvent, AuditVerification, marketplace, RoleQuality, TrustKpi } from "../lib/marketplace";
import QualityEvidence from "../components/QualityEvidence";
import { useMe } from "../lib/useMe";

function rub(value: string | number | null) { return value == null ? "Нет данных" : formatRub(value); }

export default function KpiPage() {
  const { companies, user } = useMe();
  const [companyId, setCompanyId] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [kpi, setKpi] = useState<TrustKpi | null>(null);
  const [scorecard, setScorecard] = useState<AgentScorecard | null>(null);
  const [quality, setQuality] = useState<RoleQuality | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const [scorecardError, setScorecardError] = useState<string | null>(null);
  const [qualityPending, setQualityPending] = useState(false);
  const [scorecardPending, setScorecardPending] = useState(false);
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
    setQualityError(null); setScorecardError(null); setQualityPending(true); setScorecardPending(true);
    setKpi(null); setScorecard(null); setQuality(null); setError(null); setAuditEvents([]); setAuditError(null); setVerification(null);
    marketplace.getKpi(token, companyId || undefined).then((value) => { if (active) setKpi(value); }).catch(() => { if (active) setError("Не удалось рассчитать показатели."); });
    const scorecardRequest = companyId
      ? marketplace.getAgentScorecard(token, companyId)
      : marketplace.getPlatformAgentScorecard(token);
    scorecardRequest.then((value) => { if (active) setScorecard(value); }).catch(() => { if (active) setScorecardError("Не удалось загрузить оценку работы агентов."); }).finally(()=>{if(active) setScorecardPending(false);});
    const qualityRequest = companyId
      ? marketplace.getRoleQuality(token, companyId)
      : marketplace.getPlatformRoleQuality(token);
    qualityRequest.then((value) => { if (active) setQuality(value); }).catch(() => { if (active) setQualityError("Не удалось загрузить оценку агентных ролей."); }).finally(()=>{if(active) setQualityPending(false);});
    marketplace.getAuditEvents(token, companyId || undefined)
      .then((value) => { if (active) setAuditEvents(value); })
      .catch(() => { if (active) setAuditError("Не удалось загрузить журнал решений."); });
    if (user?.is_marketplace_admin) marketplace.verifyAudit(token)
      .then((value) => { if (active) setVerification(value); })
      .catch(() => { if (active) setAuditError("Не удалось проверить цепочку журнала."); });
    return () => { active = false; };
  }, [companyId, initialized, user, refresh]);

  return <div><div className="company-row"><h1 className="page-title">Проверяемые показатели</h1><Link href="/dashboard" className="btn btn-secondary btn-sm">В личный кабинет</Link></div>
    <p className="subtitle">Показатели рассчитываются из записей операций и журнала событий.</p>
    <div className="field"><label htmlFor="kpi-company">Компания</label><select id="kpi-company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>{user?.is_marketplace_admin && <option value="">Весь маркетплейс</option>}{companies.map((company) => <option key={company.id} value={company.id}>{company.display_name}</option>)}</select></div>
    {error && <div className="alert alert-error">{error}</div>}
    {scorecardPending && <p role="status">Загрузка оценки работы агентов…</p>}
    {scorecardError && <div className="alert alert-error" role="alert">{scorecardError}<button className="btn btn-secondary" onClick={()=>setRefresh(n=>n+1)}>Повторить загрузку</button></div>}
    {qualityPending && <p role="status">Загрузка оценки агентных ролей…</p>}
    {qualityError && <div className="alert alert-error" role="alert">{qualityError}<button className="btn btn-secondary" onClick={()=>setRefresh(n=>n+1)}>Повторить загрузку</button></div>}
    {companyId && companies.find(c=>c.id===companyId)?.membership?.is_admin && <details className="workflow-details"><summary>Проверить результат агента</summary><QualityEvidence key={companyId} companyId={companyId} onSaved={()=>setRefresh(n=>n+1)} /></details>}
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
            <p>Конверсия сценария: {scorecard.offer_draft_conversion_pct == null ? "Нет данных" : `${scorecard.offer_draft_conversion_pct} %`}</p>
            <p>Среднее число правок человеком: {scorecard.average_changed_fields ?? "Нет данных"}</p><p>Открытых допустимых черновиков: {scorecard.offer_drafts_open}; исключено неполных/устаревших: {scorecard.offer_drafts_excluded}</p>
            <p>Отклонено предложений: {scorecard.offer_rejections} из {scorecard.offers_total}</p>
            <p>Сделок из черновиков этой когорты: {scorecard.deals_from_drafts}</p><p>Исходы отправленных КП когорты: выбрано {scorecard.selected_origin_offers}, открыто {scorecard.open_origin_offers}, отклонено {scorecard.rejected_origin_offers}, истекло {scorecard.expired_origin_offers}</p>
          </div>
          <div className="card">
            <h3>Контроль человека</h3>
            <p>Подтверждений человека: {scorecard.human_approvals}</p>
            <p>Заблокированных действий: {scorecard.blocked_actions}</p>
            <p>Проверок допуска: {scorecard.admission_checks}</p>
            <p>Остановлено на допуске: {scorecard.admission_blocked}</p>
            <p>Рекомендации: {scorecard.recommendations_converted} из {scorecard.recommendations_total} ({scorecard.recommendation_conversion_pct == null ? "Нет данных" : `${scorecard.recommendation_conversion_pct} %`})</p>
          </div>
          <div className="card">
            <h3>Модель</h3>
            {scorecard.llm_metrics_available ? (
              <>
                <p>Запусков агентов: {scorecard.agent_runs_total}</p>
                <p>Отказов модели: {scorecard.agent_runs_failed}</p>
                <p>Локальный маршрут: {scorecard.agent_runs_local_route}; внешний: {scorecard.agent_runs_external_route}</p>
                <p>Смешанный маршрут: {scorecard.agent_runs_mixed_route}; по правилам: {scorecard.agent_runs_rules_route}; не определён: {scorecard.agent_runs_unknown_route}</p>
                <p>Средняя длительность: {scorecard.agent_average_duration_ms == null ? "Нет данных" : `${scorecard.agent_average_duration_ms} мс`} ({scorecard.agent_timed_runs} из {scorecard.agent_runs_total})</p>
                <p>Модели: {scorecard.agent_model_versions.length ? scorecard.agent_model_versions.join(", ") : "Нет данных"}</p>
                <p>Версии промптов: {scorecard.agent_prompt_versions.length ? scorecard.agent_prompt_versions.join(", ") : "Нет данных"}</p>
                <p>Известные оценки затрат: {scorecard.agent_costed_runs ? rub(scorecard.agent_estimated_cost_rub) : "Нет данных"} ({scorecard.agent_costed_runs} из {scorecard.agent_runs_total} запусков)</p>
              </>
            ) : (
              <p className="hint">Журнал вызовов LLM Gateway недоступен: метрики модели не рассчитаны.</p>
            )}
          </div>
        </div>
        {scorecard.notes.length > 0 && (
          <details><summary>Методика расчёта</summary><ul className="company-list">{scorecard.notes.map((note) => <li key={note}><span className="company-meta">{note}</span></li>)}</ul></details>
        )}
      </section>
    )}
    {quality && (
      <section className="card">
        <h2>Оценка агентных ролей</h2>
        <p className="hint">
          Методика {quality.method_version}: минимум {quality.min_observations} наблюдений на роль.
          Итогового балла нет: аспекты не компенсируют друг друга. Эталон — банк задач
          ({quality.benchmark.available ? `${quality.benchmark.tasks} задач` : "банк недоступен"}){quality.benchmark.available ? "" : ", точечные проверки выполняются вручную"}.
        </p>
        {quality.roles.length === 0 ? <p className="hint">Прогонов за период нет: роли не оценены.</p> : (
          <div className="form-grid">{quality.roles.map(item => <div className="card" key={item.cohort_key}>
            <h3>{item.role === "buyer_agent" ? "Агент покупателя" : item.role === "seller_agent" ? "Агент продавца" : "Агент"} · {item.status === "evaluated" ? "Оценена" : "Не оценено"}</h3>
            <p className="hint">{item.passport}</p>
            <p>Наблюдений: {item.sample} · экспертно проверено: {item.expert_verified_runs} · исходный снимок: {item.initial_result_known_runs}</p>
            <p>Класс задачи: {russianLabel(item.task_scope, "Класс проверен")}</p>
            <p>Открытых: {item.open_runs} · ошибок: {item.failed_runs} · резервных маршрутов: {item.fallback_runs}</p>
            <p>Модель: {item.model_versions.join(", ") || "Нет данных"} · промпт: {item.prompt_versions.join(", ") || "Нет данных"}</p>
            <p>Конфликты исходного результата: {item.conflicts_found} · исправления: {item.human_corrections} (источник известен для {item.corrections_known_runs} из {item.sample})</p>
            {item.status === "evaluated" ? <>
              <p>Успешных сценариев: {item.completed_runs} ({item.completed_share_pct} %)</p>
              <p>Полнота критичных полей: {item.critical_completeness_pct == null ? "Нет данных" : `${item.critical_completeness_pct} % (${item.critical_fields_confirmed} из ${item.critical_fields_total})`}</p>
              <p>Правильность критичных полей: {item.critical_correctness_pct == null ? "Нет данных" : `${item.critical_correctness_pct} % (${item.critical_fields_correct} из ${item.critical_fields_total})`}</p>
              <p>Выявлено конфликтов: {item.conflicts_found}</p>
              <p>Прогонов с уточнениями: {item.clarification_runs}</p>
              <p>Исправлений человеком: {item.human_corrections}</p>
              <p>Заблокированных действий: {item.blocked_actions}</p>
              <p>Среднее время: {item.average_duration_ms == null ? "Нет данных" : `${item.average_duration_ms} мс`}</p>
              <p>Известная стоимость: {item.known_cost_rub == null ? "Нет данных" : rub(item.known_cost_rub)} ({item.costed_share_pct} % запусков)</p>
              <p>Модели: {item.model_versions.length ? item.model_versions.join(", ") : "Нет данных"}</p>
              <p>Промпты: {item.prompt_versions.length ? item.prompt_versions.join(", ") : "Нет данных"}</p>
            </> : <p className="hint">Нужно не менее пяти завершённых экспертно проверенных прогонов с одинаковой моделью, промптом, маршрутом и классом задачи.</p>}
          </div>)}</div>
        )}
        {quality.notes.length > 0 && (
          <details><summary>Как оценено качество</summary><ul className="company-list">{quality.notes.map((note) => <li key={note}><span className="company-meta">{note}</span></li>)}</ul></details>
        )}
      </section>
    )}
    {kpi && <><div className="form-grid"><div className="card"><h2>Покупатель</h2><p>Созданная ценность: {kpi.buyer.value_events ? rub(kpi.buyer.created_value_rub) : "Нет данных для сравнения"}</p><p>Подтверждений: {kpi.buyer.human_approvals ?? 0}</p></div><div className="card"><h2>Производитель</h2><p>Созданная ценность: {kpi.seller.value_events ? rub(kpi.seller.created_value_rub) : "Нет данных для сравнения"}</p></div><div className="card"><h2>Маркетплейс</h2><p>Объём сделок: {rub(kpi.marketplace.gmv_rub ?? 0)}</p><p>Событий: {kpi.generated_from_events}</p></div></div><p className="hint">{kpi.baseline_note}</p></>}
    <section className="card"><h2>Журнал решений</h2>
      <p className="hint">Последние 50 событий выбранной компании. Запись показывает действие и его причину; история другой компании недоступна.</p>
      {verification && <p role="status">Проверка последовательности и хешей: {verification.valid ? `успешна, ${verification.checked_events} событий` : `ошибка на событии № ${verification.broken_sequence}`}. Это не защита от изменения базы администратором.</p>}
      {auditError && <div className="alert alert-error">{auditError}</div>}
      {!auditError && auditEvents.length === 0 ? <p className="hint">Событий пока нет.</p> : <ul className="company-list">{auditEvents.map((event) => <li key={event.id} className="company-item"><strong>№ {event.sequence} · {russianLabel(event.event_type, "Действие платформы")}</strong><span className="company-meta">{new Date(event.created_at).toLocaleString("ru-RU")} · {russianLabel(event.entity_type, "Запись")}{event.entity_id ? ` · ${event.entity_id}` : ""}</span><p>{event.explanation}</p></li>)}</ul>}
    </section>
  </div>;
}

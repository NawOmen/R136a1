"use client";
import { russianMessage } from "../lib/russianMessages";
import { russianLabel } from "../lib/presentation";
import CommercialEstimate from "../components/CommercialEstimate";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { ApiError, formatRub, formatUnits, marketplace, ResiliencePlan } from "../lib/marketplace";

const planStatuses: Record<string, string> = {
  stale: "Спецификация изменилась", preparing_reserves: "Подготовка резерва",
  ready_for_confirmation: "Ожидает согласования", active: "План действует",
  partially_covered: "Объём покрыт частично", awaiting_reserve_reconfirmation: "Нужно подтверждение резерва",
  recovery_proposed: "Замена готова к согласованию", recovered: "Поставка восстановлена",
};

export default function ResiliencePage() {
  const [plans, setPlans] = useState<ResiliencePlan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);

  async function reload() {
    const token = getToken();
    if (token) setPlans(await marketplace.getResiliencePlans(token));
  }

  useEffect(() => {
    void reload().catch((err: unknown) =>
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить планы."),
    ).finally(() => setLoading(false));
  }, []);

  async function confirm(plan: ResiliencePlan) {
    const token = getToken();
    if (!token || !window.confirm("Подтвердить план и заданные пороги замены?")) return;
    if (working) return;
    setError(null);
    setWorking(plan.id);
    try { await marketplace.confirmResiliencePlan(token, plan.id, plan.version); await reload(); }
    catch (err) { setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось подтвердить план."); }
    finally { setWorking(null); }
  }

  async function simulate(plan: ResiliencePlan, companyIds: string[]) {
    const token = getToken();
    if (!token) return;
    if (working) return;
    setError(null);
    setWorking(plan.id);
    try {
      const scenario = await marketplace.simulateFailure(token, plan.id, companyIds);
      window.alert(
        `Безопасная симуляция: покрыто ${formatUnits(scenario.result.confirmed_covered_units)}, ` +
        `дефицит ${formatUnits(scenario.result.uncovered_units)}, изменение полной цены ${scenario.result.cost_comparison_applicable ? formatRub(scenario.result.price_delta_rub) : "неприменимо"}, ` +
        `задержка ${scenario.result.delay_days} дн. Сделка не изменена.`,
      );
      await reload();
    } catch (err) { setError(err instanceof ApiError ? russianMessage(err.message) : "Симуляция не выполнена."); }
    finally { setWorking(null); }
  }

  async function approveRecovery(plan: ResiliencePlan, scenarioId: string) {
    const token = getToken();
    if (!token || !window.confirm(`Активировать рассчитанную замену производителя по версии ${plan.version}?`)) return;
    if (working) return;
    setError(null);
    setWorking(plan.id);
    try { await marketplace.approveRecovery(token, scenarioId, plan.version); await reload(); }
    catch (err) { setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось активировать замену."); }
    finally { setWorking(null); }
  }

  async function recalculate(plan: ResiliencePlan) {
    const token = getToken();
    if (!token || working) return;
    setError(null);
    setWorking(plan.id);
    try { await marketplace.recalculateResiliencePlan(token, plan.id); await reload(); }
    catch (err) { setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось пересчитать план."); }
    finally { setWorking(null); }
  }

  return (
    <div>
      <div className="company-row">
        <div><h1 className="page-title">Устойчивость сделок</h1><p className="subtitle">Резервные производители и восстановление поставки</p></div>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {loading ? <p role="status">Загрузка планов…</p> : plans.length === 0 && !error ? <p className="hint">Планов нет. Рассчитайте варианты в карточке потребности и выберите выполнимый.</p> : plans.map((plan) => {
        const n1 = plan.scenarios.filter((item) => item.scenario_type === "n1" && item.status === "calculated" && item.is_current);
        const n2 = plan.scenarios.filter((item) => item.scenario_type === "n2" && item.status === "calculated" && item.is_current);
        return <section className="card" key={plan.id}>
          <div className="company-row"><h2>План #{plan.id.slice(0, 8)}</h2><span className="badge">{planStatuses[plan.status] ?? "Требуется уточнение"}</span></div>
          {plan.status === "stale" && <p className="alert alert-error">Прежние расчёты сохранены для истории. <Link href={`/needs/${plan.need_id}`}>Получите новые КП и создайте ресурсный план по текущей спецификации.</Link></p>}
          <p>Исходная конфигурация: {formatRub(plan.baseline_total_cost_rub)} · {plan.baseline_lead_time_days} дн. · версия {plan.version}</p>
          <p>Текущая полная смета: {formatRub(plan.current_total_cost_rub)} · {plan.current_lead_time_days} дн.</p>
          {plan.commercial_snapshot && <p>Уже согласованное удержание резерва: {formatRub(plan.commercial_snapshot.reserve_holding_total_rub)}. Оно остаётся понесённым расходом при отмене и входит в итог; новые удержания согласуются отдельно.</p>}
          {!plan.confirmed_at && plan.commercial_snapshot && <p className="alert alert-error">Смета изменилась. До повторного согласия замена не активируется.</p>}
          <p className="hint">Автозамена: {plan.auto_replace_within_thresholds ? "разрешена" : "требует подтверждения"}; пороги: +{plan.max_price_increase_pct}% и +{plan.max_delay_days} дн.</p>
          <div className="market-grid">
            <div><strong>Основные: {plan.baseline_allocations.length}</strong><p className="hint">{plan.baseline_allocations.map((a) => `#${a.company_id.slice(0, 8)} — ${formatUnits(a.units)}`).join("; ")}</p></div>
            <div><strong>Резерв: {plan.reserves.length}</strong><p className="hint">горячий: {plan.reserves.filter((r) => r.effective_tier === "hot").length}; тёплый: {plan.reserves.filter((r) => r.effective_tier === "warm").length}; холодный: {plan.reserves.filter((r) => r.effective_tier === "cold").length}</p></div>
          </div>
          {plan.baseline_allocations.map(item=><div key={item.company_id}><p>Смета основного поставщика #{item.company_id.slice(0,8)}</p><CommercialEstimate value={item.commercial_snapshot?.estimate} /></div>)}
          {plan.reserves.filter(item=>item.confirmation_status === "approved").map(item=><div key={item.id}><p>КП резерва #{item.company_id.slice(0,8)} ({item.effective_tier === "hot" ? "горячий, подтверждённый" : "требует подтверждения — не гарантированный объём"}; удержание до {item.held_until ?? "—"}{item.switchover_days != null ? `; переключение за ${item.switchover_days} дн.` : ""}). {item.availability_reason && <span className="hint"> {item.availability_reason}.</span>} Доступно: {formatUnits(item.available_units)}. При переключении плата за уже согласованное удержание повторно не начисляется.</p><CommercialEstimate value={item.commercial_snapshot?.estimate} /></div>)}
          {plan.current_allocations.map((item, index) => <p key={`${item.company_id}-${index}`}>Текущее назначение #{item.company_id.slice(0, 8)}: {formatUnits(item.units)}{item.role === "executed" ? " · уже исполнено" : ""}{item.deal_id && <> · <Link href="/deals">Отгрузка и приёмка в сделках</Link></>}</p>)}
          {plan.scenarios.some(item => item.status === "calculated" && !item.is_current) && <p className="alert alert-error">Расчёт устарел: условия резерва или исполнение изменились. Пересчитайте план перед подтверждением.</p>}
          <p><strong>N-1:</strong> {n1.length} сценариев · <strong>N-2:</strong> {n2.length} сценариев</p>
          <ul className="evidence-list">{[...n1, ...n2].map((s) => <li key={s.id}>{russianLabel(s.scenario_type, "Сценарий отказа")} ({s.failed_company_ids.map((id) => `#${id.slice(0, 8)}`).join(" + ")}): подтверждено {formatUnits(s.result.confirmed_covered_units)}, дефицит {formatUnits(s.result.uncovered_units)}, изменение полной цены {s.result.cost_comparison_applicable ? formatRub(s.result.price_delta_rub) : "неприменимо"}, +{s.result.delay_days} дн.{s.result.solver_status === "timeout" ? " · расчёт не уложился в лимит: это не отсутствие решения" : ""}{s.result.solver_status === "infeasible" ? " · допустимого распределения нет" : ""}</li>)}</ul>
          <div className="actions">
            <button className="btn btn-secondary btn-sm" disabled={working !== null || plan.status === "stale"} onClick={() => void recalculate(plan)}>Пересчитать резерв</button>
            {plan.status === "ready_for_confirmation" && <button className="btn btn-success" disabled={working !== null} onClick={() => void confirm(plan)}>Подтвердить план</button>}
            {plan.baseline_allocations.map((a) => <button key={a.company_id} className="btn btn-secondary btn-sm" disabled={working !== null || plan.status === "stale"} onClick={() => void simulate(plan, [a.company_id])}>Симуляция отказа #{a.company_id.slice(0, 8)}</button>)}
            {plan.baseline_allocations.length > 1 && <button className="btn btn-secondary btn-sm" disabled={working !== null || plan.status === "stale"} onClick={() => void simulate(plan, plan.baseline_allocations.slice(0, 2).map((a) => a.company_id))}>Симуляция двух отказов</button>}
            {plan.scenarios.filter((s) => s.status === "proposed").map((scenario) => <button key={scenario.id} className="btn btn-success btn-sm" disabled={working !== null || plan.status === "stale" || !scenario.is_current || scenario.result.uncovered_units > 0 || scenario.result.unconfirmed_units > 0} onClick={() => void approveRecovery(plan, scenario.id)}>Подтвердить замену остатка</button>)}
          </div>
        </section>;
      })}
    </div>
  );
}

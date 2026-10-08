"use client";
import CommercialEstimate from "../components/CommercialEstimate";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { ApiError, formatRub, formatUnits, marketplace, ResiliencePlan } from "../lib/marketplace";

export default function ResiliencePage() {
  const [plans, setPlans] = useState<ResiliencePlan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);

  async function reload() {
    const token = getToken();
    if (token) setPlans(await marketplace.getResiliencePlans(token));
  }

  useEffect(() => {
    void reload().catch((err: unknown) =>
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить планы."),
    );
  }, []);

  async function confirm(plan: ResiliencePlan) {
    const token = getToken();
    if (!token || !window.confirm("Подтвердить план и заданные пороги замены?")) return;
    setWorking(plan.id);
    try { await marketplace.confirmResiliencePlan(token, plan.id, plan.version); await reload(); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Не удалось подтвердить план."); }
    finally { setWorking(null); }
  }

  async function simulate(plan: ResiliencePlan, companyIds: string[]) {
    const token = getToken();
    if (!token) return;
    setWorking(plan.id);
    try {
      const scenario = await marketplace.simulateFailure(token, plan.id, companyIds);
      window.alert(
        `Безопасная симуляция: покрыто ${formatUnits(scenario.result.confirmed_covered_units)}, ` +
        `дефицит ${formatUnits(scenario.result.uncovered_units)}, изменение полной цены ${scenario.result.cost_comparison_applicable ? formatRub(scenario.result.price_delta_rub) : "неприменимо"}, ` +
        `задержка ${scenario.result.delay_days} дн. Сделка не изменена.`,
      );
      await reload();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Симуляция не выполнена."); }
    finally { setWorking(null); }
  }

  async function approveRecovery(plan: ResiliencePlan, scenarioId: string) {
    const token = getToken();
    if (!token || !window.confirm("Активировать рассчитанную замену производителя?")) return;
    setWorking(plan.id);
    try { await marketplace.approveRecovery(token, scenarioId); await reload(); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Не удалось активировать замену."); }
    finally { setWorking(null); }
  }

  return (
    <div>
      <div className="company-row">
        <div><h1 className="page-title">Устойчивость сделок</h1><p className="subtitle">Резервы и расчёт отказов обычным кодом, без решений LLM</p></div>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {plans.length === 0 ? <p className="hint">Планов нет. Рассчитайте варианты в карточке потребности и выберите выполнимый.</p> : plans.map((plan) => {
        const n1 = plan.scenarios.filter((item) => item.scenario_type === "n1" && item.status === "calculated");
        const n2 = plan.scenarios.filter((item) => item.scenario_type === "n2" && item.status === "calculated");
        return <section className="card" key={plan.id}>
          <div className="company-row"><h2>План #{plan.id.slice(0, 8)}</h2><span className="badge">{plan.status}</span></div>
          <p>{formatRub(plan.baseline_total_cost_rub)} · {plan.baseline_lead_time_days} дн. · версия {plan.version}</p>
          {plan.commercial_snapshot && <p>Уже согласованное удержание резерва: {formatRub(plan.commercial_snapshot.reserve_holding_total_rub)}. Оно остаётся понесённым расходом при отмене и входит в итог; новые удержания согласуются отдельно.</p>}
          {!plan.confirmed_at && plan.commercial_snapshot && <p className="alert alert-error">Смета изменилась. До повторного согласия замена не активируется.</p>}
          <p className="hint">Автозамена: {plan.auto_replace_within_thresholds ? "разрешена" : "требует подтверждения"}; пороги: +{plan.max_price_increase_pct}% и +{plan.max_delay_days} дн.</p>
          <div className="market-grid">
            <div><strong>Основные: {plan.baseline_allocations.length}</strong><p className="hint">{plan.baseline_allocations.map((a) => `#${a.company_id.slice(0, 8)} — ${formatUnits(a.units)}`).join("; ")}</p></div>
            <div><strong>Резерв: {plan.reserves.length}</strong><p className="hint">горячий: {plan.reserves.filter((r) => r.reserve_tier === "hot").length}; тёплый: {plan.reserves.filter((r) => r.reserve_tier === "warm").length}; холодный: {plan.reserves.filter((r) => r.reserve_tier === "cold").length}</p></div>
          </div>
          {plan.baseline_allocations.map(item=><div key={item.company_id}><p>Смета основного поставщика #{item.company_id.slice(0,8)}</p><CommercialEstimate value={item.commercial_snapshot?.estimate} /></div>)}
          {plan.reserves.filter(item=>item.confirmation_status === "approved").map(item=><div key={item.id}><p>КП резерва #{item.company_id.slice(0,8)}. При переключении плата за уже согласованное удержание повторно не начисляется.</p><CommercialEstimate value={item.commercial_snapshot?.estimate} /></div>)}
          <p><strong>N-1:</strong> {n1.length} сценариев · <strong>N-2:</strong> {n2.length} сценариев</p>
          <ul className="evidence-list">{[...n1, ...n2].map((s) => <li key={s.id}>{s.scenario_type} ({s.failed_company_ids.map((id) => `#${id.slice(0, 8)}`).join(" + ")}): подтверждено {formatUnits(s.result.confirmed_covered_units)}, дефицит {formatUnits(s.result.uncovered_units)}, изменение полной цены {s.result.cost_comparison_applicable ? formatRub(s.result.price_delta_rub) : "неприменимо"}, +{s.result.delay_days} дн.</li>)}</ul>
          <div className="actions">
            {plan.status === "ready_for_confirmation" && <button className="btn btn-success" disabled={working === plan.id} onClick={() => void confirm(plan)}>Подтвердить план</button>}
            {plan.baseline_allocations.map((a) => <button key={a.company_id} className="btn btn-secondary btn-sm" disabled={working === plan.id} onClick={() => void simulate(plan, [a.company_id])}>Симуляция отказа #{a.company_id.slice(0, 8)}</button>)}
            {plan.baseline_allocations.length > 1 && <button className="btn btn-secondary btn-sm" disabled={working === plan.id} onClick={() => void simulate(plan, plan.baseline_allocations.slice(0, 2).map((a) => a.company_id))}>Симуляция двух отказов</button>}
            {plan.scenarios.filter((s) => s.status === "proposed").map((scenario) => <button key={scenario.id} className="btn btn-success btn-sm" disabled={working === plan.id || scenario.result.uncovered_units > 0 || scenario.result.unconfirmed_units > 0} onClick={() => void approveRecovery(plan, scenario.id)}>Подтвердить полную замену</button>)}
          </div>
        </section>;
      })}
    </div>
  );
}

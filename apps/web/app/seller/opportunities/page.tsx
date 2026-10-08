"use client";
import CommercialTermsFields, { emptyCommercialTerms } from "../../components/CommercialTermsFields";
import type { CommercialTerms } from "../../lib/marketplace";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  Coalition,
  formatRub,
  formatUnits,
  GroupOffer,
  MarketOpportunity,
  marketplace,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

type MemberTerms = Record<
  string,
  { individual: string; delivery: string; baseline: string; deliveryDays: string }
>;

export default function MarketOpportunitiesPage() {
  const { loading, error: meError, available, companyId, setCompanyId } =
    useCompanySelector("can_sell");
  const [items, setItems] = useState<MarketOpportunity[]>([]);
  const [coalitions, setCoalitions] = useState<Coalition[]>([]);
  const [draft, setDraft] = useState<GroupOffer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [unitPrice, setUnitPrice] = useState("10.9");
  const [capacity, setCapacity] = useState("60000");
  const [productionStart, setProductionStart] = useState("");
  const [productionEnd, setProductionEnd] = useState("");
  const [fillDeadline, setFillDeadline] = useState("");
  const [commercialTerms, setCommercialTerms] = useState<Record<string,CommercialTerms>>({});
  const [sharedCost, setSharedCost] = useState("0");
  const [memberTerms, setMemberTerms] = useState<MemberTerms>({});

  async function reload() {
    const token = getToken();
    if (!token || !companyId) return;
    const [opportunities, currentCoalitions] = await Promise.all([
      marketplace.getMarketOpportunities(token, companyId),
      marketplace.getCoalitions(token),
    ]);
    setItems(opportunities);
    setCoalitions(currentCoalitions);
  }

  useEffect(() => {
    if (!companyId) return;
    setError(null);
    void reload().catch((err: unknown) =>
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить возможности."),
    );
    // reload использует только выбранную компанию.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  async function prepare(item: MarketOpportunity) {
    const token = getToken();
    if (!token) return;
    setWorking(true);
    setError(null);
    try {
      const prepared = await marketplace.prepareGroupOffer(token, item.id);
      setDraft(prepared);
      const currentCoalitions = await marketplace.getCoalitions(token);
      setCoalitions(currentCoalitions);
      const coalition = currentCoalitions.find((entry) => entry.id === prepared.coalition_id);
      if (coalition) {
        setCommercialTerms(Object.fromEntries(coalition.members.map(member=>[member.need_id,{...emptyCommercialTerms}])));
        setMemberTerms(
          Object.fromEntries(
            coalition.members.map((member) => [
              member.need_id,
              { individual: "0", delivery: "", baseline: "", deliveryDays: "1" },
            ]),
          ),
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось подготовить черновик.");
    } finally {
      setWorking(false);
    }
  }

  function updateMember(needId: string, key: keyof MemberTerms[string], value: string) {
    setMemberTerms((current) => ({
      ...current,
      [needId]: { ...current[needId], [key]: value },
    }));
  }

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    const coalition = coalitions.find((item) => item.id === draft?.coalition_id);
    if (!token || !draft || !coalition) return;
    if (!window.confirm("Подтвердить цену, мощность и групповые условия производителя?")) return;
    setWorking(true);
    setError(null);
    try {
      await marketplace.publishGroupOffer(token, draft.id, {
        shared_cost_rub: sharedCost,
        min_total_units: draft.min_total_units ?? coalition.target_moq_units ?? 1,
        max_total_units: draft.max_total_units ?? coalition.combined_volume_units,
        available_capacity_units: Number(capacity),
        price_tiers: [
          {
            min_units: draft.min_total_units ?? coalition.target_moq_units ?? 1,
            unit_price_rub: String(unitPrice),
          },
        ],
        production_start: productionStart,
        production_end: productionEnd,
        fill_deadline: fillDeadline,
        non_fill_rule: "close_without_obligations",
        participant_terms: coalition.members.map((member) => ({
          need_id: member.need_id,
          commercial_terms: commercialTerms[member.need_id],
          individual_operations_cost_rub: String(memberTerms[member.need_id]?.individual ?? 0),
          delivery_cost_rub: commercialTerms[member.need_id]?.delivery_method === "separate" ? (memberTerms[member.need_id]?.delivery || null) : "0",
          individual_baseline_cost_rub: null,
          delivery_days: Number(memberTerms[member.need_id]?.deliveryDays ?? 1),
        })),
      });
      setDraft(null);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось опубликовать предложение.");
    } finally {
      setWorking(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError || available.length === 0) {
    return <div className="alert alert-error">{meError ?? "Нет компании с правом продажи."}</div>;
  }

  const draftCoalition = coalitions.find((item) => item.id === draft?.coalition_id);

  return (
    <div>
      <div className="company-row">
        <div>
          <h1 className="page-title">Что сейчас нужно рынку</h1>
          <p className="subtitle">Подтверждённый незакрытый спрос, подходящий вашему производству</p>
        </div>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link>
      </div>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="opportunity_company">Компания</label>
          <select id="opportunity_company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
            {available.map((company) => <option key={company.id} value={company.id}>{company.display_name}</option>)}
          </select>
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}

      {items.length === 0 ? (
        <p className="hint">Активных дефицитных возможностей сейчас нет: спрос закрыт либо не соответствует паспорту возможностей.</p>
      ) : (
        <div className="market-grid">
          {items.map((item) => (
            <article className="card" key={item.id}>
              <div className="company-row">
                <h2>{item.category}</h2>
                <span className="opportunity-score">{item.score}/100</span>
              </div>
              <p>
                {item.unmet_volume_units === null
                  ? "Объём скрыт: для безопасной агрегации недостаточно независимых покупателей"
                  : `Незакрытый спрос: ${formatUnits(item.unmet_volume_units, item.unit)}`}
              </p>
              <p className="company-meta">
                Покупателей: {item.buyers_count} · Конкуренция: {item.competition_level} · Риск насыщения: {item.saturation_risk}
              </p>
              <ul>{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              <p className="hint">Экономика не рассчитана: {item.missing_data.join(", ")}. Это рыночная возможность, не гарантия прибыли.</p>
              <button type="button" className="btn btn-primary" disabled={working} onClick={() => void prepare(item)}>
                Подготовить предложение
              </button>
            </article>
          ))}
        </div>
      )}

      {draft && draftCoalition && (
        <form className="card" onSubmit={(event) => void publish(event)}>
          <h2>Черновик группового предложения</h2>
          <p className="hint">
            Черновик создан без цены и публикации. Заполните условия и подтвердите их вручную.
          </p>
          <div className="form-grid">
            <div className="field"><label>Цена за единицу, ₽</label><input type="number" step="any" min="0.000000000001" required value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} /></div>
            <div className="field"><label>Подтверждённая мощность, {draftCoalition.unit}</label><input type="number" min="1" required value={capacity} onChange={(e) => setCapacity(e.target.value)} /></div>
            <div className="field"><label>Окончание набора</label><input type="date" required value={fillDeadline} onChange={(e) => setFillDeadline(e.target.value)} /></div>
            <div className="field"><label>Начало производства</label><input type="date" required value={productionStart} onChange={(e) => setProductionStart(e.target.value)} /></div>
            <div className="field"><label>Окончание производства</label><input type="date" required value={productionEnd} onChange={(e) => setProductionEnd(e.target.value)} /></div>
          </div>
          <h3>Отдельные условия покупателей</h3>
          {draftCoalition.members.map((member, index) => (
            <div className="participant-terms" key={member.need_id}>
              <CommercialTermsFields value={commercialTerms[member.need_id]??emptyCommercialTerms} onChange={value=>setCommercialTerms(current=>({...current,[member.need_id]:value}))} disabled={working} />
              <strong>Участник {index + 1} · {formatUnits(member.units, draftCoalition.unit)}</strong>
              <div className="form-grid">
                <div className="field"><label>Индивидуальные операции, ₽</label><input type="number" min="0" required value={memberTerms[member.need_id]?.individual ?? ""} onChange={(e) => updateMember(member.need_id, "individual", e.target.value)} /></div>
                <div className="field"><label>Отдельная доставка, ₽</label><input type="number" min="0" required value={memberTerms[member.need_id]?.delivery ?? ""} onChange={(e) => updateMember(member.need_id, "delivery", e.target.value)} /></div>
                <p className="hint">Сопоставимое подтверждённое КП выбирает сам покупатель в своей коалиции.</p>
                <div className="field"><label>Доставка, дней</label><input type="number" min="0" required value={memberTerms[member.need_id]?.deliveryDays ?? "1"} onChange={(e) => updateMember(member.need_id, "deliveryDays", e.target.value)} /></div>
              </div>
            </div>
          ))}
          <label>Общие расходы на запуск партии, ₽<input type="number" min="0" step="0.01" required value={sharedCost} onChange={event=>setSharedCost(event.target.value)}/></label>
          <p className="hint">Итого партии: {formatUnits(draftCoalition.combined_volume_units, draftCoalition.unit)}. Цена, логистика и выгода будут проверены отдельно для каждого участника обычным кодом.</p>
          <div className="actions">
            <button type="submit" className="btn btn-success" disabled={working}>Проверить и направить участникам</button>
            <button type="button" className="btn btn-secondary" onClick={() => setDraft(null)}>Закрыть черновик</button>
          </div>
        </form>
      )}
    </div>
  );
}

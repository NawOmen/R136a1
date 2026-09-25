"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { ApiError, Coalition, formatRub, formatUnits, marketplace } from "../lib/marketplace";
import { useMe } from "../lib/useMe";

const STATUS_LABELS: Record<string, string> = {
  candidate: "Кандидат на объединение",
  awaiting_approvals: "Ожидает подтверждений",
  confirmed: "Условия подтверждены всеми",
  recalculation_required: "Требуется пересчёт",
  expired: "Срок набора истёк",
  cancelled: "Закрыта без обязательств",
};

export default function CoalitionsPage() {
  const me = useMe();
  const [items, setItems] = useState<Coalition[]>([]);
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    marketplace
      .getCoalitions(token)
      .then(setItems)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Не удалось загрузить коалиции."),
      )
      .finally(() => setLoading(false));
  }, []);

  async function decide(coalition: Coalition, companyId: string, decision: "approved" | "rejected") {
    const token = getToken();
    if (!token) return;
    const message =
      decision === "approved"
        ? "Подтвердить только условия вашей компании? Вы не подтверждаете условия других покупателей."
        : "Отказаться от групповых условий? Вариант будет пересчитан без автоматических обязательств.";
    if (!window.confirm(message)) return;
    setWorkingId(coalition.id);
    setError(null);
    try {
      const updated = await marketplace.decideCoalition(token, coalition.id, companyId, decision, coalition.version);
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить решение.");
    } finally {
      setWorkingId(null);
    }
  }

  if (loading || me.loading) return <p className="hint">Загрузка...</p>;

  const buyerCompanyIds = new Set(
    me.companies.filter((company) => company.membership?.can_buy).map((company) => company.id),
  );

  return (
    <div>
      <div className="company-row">
        <div>
          <h1 className="page-title">Объединённые партии</h1>
          <p className="subtitle">Отдельные условия и подтверждения каждого участника</p>
        </div>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {items.length === 0 ? (
        <p className="hint">Подходящих объединённых партий пока нет.</p>
      ) : (
        <div className="market-grid">
          {items.map((coalition) => {
            const ownMember = coalition.members.find(
              (member) => member.buyer_company_id && buyerCompanyIds.has(member.buyer_company_id),
            );
            return (
              <article className="card" key={coalition.id}>
                <div className="company-row">
                  <h2>{coalition.category}</h2>
                  <span className={`badge badge-${coalition.status}`}>
                    {STATUS_LABELS[coalition.status] ?? coalition.status}
                  </span>
                </div>
                <p>
                  Общая партия: {formatUnits(coalition.combined_volume_units, coalition.unit)} · MOQ: {coalition.target_moq_units ? formatUnits(coalition.target_moq_units, coalition.unit) : "—"}
                </p>
                <ul>{coalition.explanation.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                {ownMember && (
                  <section className="participant-terms">
                    <h3>Условия вашей компании</h3>
                    <p>Ваш объём: {formatUnits(ownMember.units, coalition.unit)}</p>
                    <p>
                      Общая часть: {formatRub(ownMember.common_cost_rub)} · Индивидуальные операции: {formatRub(ownMember.individual_cost_rub)} · Логистика: {formatRub(ownMember.delivery_cost_rub)}
                    </p>
                    <p>
                      Итого: {formatRub(ownMember.total_cost_rub)} · Эффект относительно альтернативы: {ownMember.benefit_rub === null ? "база сравнения отсутствует" : formatRub(ownMember.benefit_rub)}
                    </p>
                    <p className="hint">Решение вашей компании: {ownMember.approval_status}</p>
                    {coalition.status === "awaiting_approvals" && ownMember.approval_status === "pending" && (
                      <div className="actions">
                        <button type="button" className="btn btn-success" disabled={workingId === coalition.id} onClick={() => void decide(coalition, ownMember.buyer_company_id!, "approved")}>Подтвердить свои условия</button>
                        <button type="button" className="btn btn-secondary" disabled={workingId === coalition.id} onClick={() => void decide(coalition, ownMember.buyer_company_id!, "rejected")}>Отказаться</button>
                      </div>
                    )}
                  </section>
                )}
                <p className="hint">
                  Другие покупатели имеют отдельные бюджеты, контакты и заказы. Сделка не создаётся, пока каждый участник не подтвердит собственные условия.
                </p>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

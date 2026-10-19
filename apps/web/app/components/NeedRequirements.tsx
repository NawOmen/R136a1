"use client";

import { formatDateTime } from "../lib/dates";

import { displayValue } from "../lib/presentation";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { marketplace, Need, characteristicLabel } from "../lib/marketplace";
import RequirementSource from "./RequirementSource";

export default function NeedRequirements({ need }: { need: Need }) {
  const [history, setHistory] = useState<Awaited<ReturnType<typeof marketplace.needRevisions>>>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false; const token = getToken();
    setHistory([]); setError("");
    if (token) void marketplace.needRevisions(token, need.id).then(value => { if (!cancelled) setHistory(value); }).catch(() => { if (!cancelled) setError("Не удалось загрузить историю версий"); });
    return () => { cancelled = true; };
  }, [need.id, need.revision]);
  const evidence = need.requirements_evidence;
  const labels: Record<string, string> = { quantity_units: "Количество", budget_rub: "Бюджет, ₽", deadline_date: "Срок поставки", category: "Категория", subcategory: "Подкатегория", delivery_address_id: "Адрес доставки", volume_units: "Количество", valid_until: "Актуальность", characteristics: "Характеристики", evidence: "Подтверждение требований" };
  const label = (key: string) => labels[key] ?? characteristicLabel(key, need.category_profile);
  const show = (value: unknown) => value == null || value === "" ? "Не указано" : displayValue(value);
  return <section className="card">
    <h2>Требования и история версий</h2>
    <p>Текущая версия: {need.revision}</p>
    {evidence?.stale && <p className="alert alert-error" role="alert">Источник изменён или удалён. Подтвердите новую версию спецификации перед публикацией и выбором КП.</p>}
    {evidence ? Object.entries(evidence.fields).map(([key, field]) => <details key={key}>
      <summary>{label(key)}: {show(field.value)} {field.normalized_unit} · {field.origin === "agent" ? "Из материалов, проверено покупателем" : "Указано покупателем"}</summary>
      {field.original_unit && field.original_unit !== field.normalized_unit && <p>Исходное значение: {show(field.original_value)} {field.original_unit}</p>}
      <p className="hint">Подтверждено {formatDateTime(field.confirmed_at)}</p>
      {evidence.run && field.sources.map((source, index) => <RequirementSource key={`${need.id}:${evidence.run?.id}:${source.source_id}:${index}`} runId={evidence.run!.id} source={source} />)}
    </details>) : <p className="hint">Для прежней версии отдельное происхождение полей не сохранялось.</p>}
    {error && <p role="alert">{error}</p>}
    <details><summary>Сохранённые версии ({history.length})</summary>{history.map(row => <details key={row.revision}><summary>Версия {row.revision} · {formatDateTime(row.created_at)}</summary><p>Количество: {show(row.snapshot.volume_units)} · Срок поставки: {show(row.snapshot.deadline_date)}</p>{Object.entries((row.impact.changes ?? {}) as Record<string, { before: unknown; after: unknown }>).map(([key, value]) => <p key={key}>{label(key)}: {show(value.before)} → {show(value.after)}</p>)}</details>)}</details>
  </section>;
}

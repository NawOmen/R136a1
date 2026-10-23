"use client";
import { russianMessage } from "../lib/russianMessages";
import { russianLabel } from "../lib/presentation";
import { useEffect, useState } from "react";
import { russianUnit, formatRub, marketplace, QuantityConversionPreview } from "../lib/marketplace";

export default function PhysicalQuantityReview({ kind, values, approved, onApproval, compact = false }: {
  compact?: boolean; kind: "product" | "need"; values: Record<string, unknown>; approved: boolean; onApproval: (approved: boolean) => void;
}) {
  const [preview, setPreview] = useState<QuantityConversionPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const signature = JSON.stringify(values);
  useEffect(() => {
    let cancelled = false;
    onApproval(false); setPreview(null); setError(null); setLoading(false);
    const input = JSON.parse(signature) as Record<string, unknown>;
    if (!(kind === "need" ? input.volume_units : input.moq_units)) return;
    setLoading(true);
    const timer = window.setTimeout(() => {
      marketplace.previewPhysicalQuantity(kind, input).then((result) => { if (!cancelled) setPreview(result.conversion); })
        .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? russianMessage(err.message) : "Не удалось проверить объём."); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => { cancelled = true; window.clearTimeout(timer); };
    // Signature contains the exact reviewed values; changing them clears consent.
  }, [signature, kind, retry]);
  if (error) return <div role="alert" className="alert alert-error">{error} <button type="button" onClick={() => setRetry((value) => value + 1)}>Повторить расчёт</button></div>;
  if (loading) return <p role="status" className="hint">Проверяем точность объёма…</p>;
  if (!preview || preview.factor === 1) return compact ? null : <p className="hint">Штуки, рулоны, упаковки и комплекты — целыми числами. Физические объёмы — в том числе дробными, без округления.</p>;
  const labels: Record<string, string> = { volume_units: "Объём", moq_units: "Минимальный заказ", stock_units: "Остаток" };
  return <div className="field">
    <p className="hint">Точный пересчёт: 1 {russianUnit(preview.input_unit)} = {preview.factor} {russianUnit(preview.stored_unit)}. В заказах и ресурсах будет использоваться {russianUnit(preview.stored_unit)}.</p>
    {Object.entries(preview.quantities).map(([key, value]) => value != null && <p key={key}>{labels[key] ?? russianLabel(key)}: {value} {russianUnit(preview.stored_unit)}</p>)}
    {preview.price_rub != null && <p>Цена: {formatRub(preview.price_rub, 12)} / {russianUnit(preview.stored_unit)}</p>}
    {preview.price_tiers?.map(tier=><p key={tier.min_units}>От {tier.min_units} {russianUnit(preview.stored_unit)}: {formatRub(tier.unit_price_rub, 12)} / {russianUnit(preview.stored_unit)}</p>)}
    <label><input type="checkbox" required checked={approved} onChange={(event) => onApproval(event.target.checked)} /> Пересчёт объёма и цены проверен</label>
  </div>;
}

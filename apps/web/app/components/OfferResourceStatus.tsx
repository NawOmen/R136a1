"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { formatDateTime, formatDate } from "../lib/dates";
import { formatUnits, marketplace, type OfferResource } from "../lib/marketplace";
import { categoryLeafId } from "../lib/categoryProfiles";

export type ResourceCheck = { key: string; value?: OfferResource; error?: string };
export default function OfferResourceStatus({ needId, companyId, kind, productId, units, category, subcategory, onChange }: {
  needId: string; companyId: string; kind: "stock" | "capacity"; productId: string; units: number;
  category: string; subcategory?: string | null; onChange: (check: ResourceCheck) => void;
}) {
  const [check, setCheck] = useState<ResourceCheck | null>(null), [retry, setRetry] = useState(0);
  const key = `${needId}:${companyId}:${kind}:${productId}`;
  useEffect(() => {
    let active = true; const token = getToken(); const pending = { key };
    setCheck(pending); onChange(pending);
    if (token) marketplace.getOfferResource(token, needId, companyId, kind, productId).then(value => {
      if (active) { const next = { key, value }; setCheck(next); onChange(next); }
    }).catch((e: Error) => { if (active) { const next = { key, error: e.message }; setCheck(next); onChange(next); } });
    return () => { active = false; };
  }, [key, retry, onChange]);
  const value = check?.key === key ? check.value : undefined;
  const error = check?.key === key ? check.error : undefined;
  const leaf = categoryLeafId(category, subcategory ?? "");
  const destination = kind === "stock" ? "/seller/products" : `/seller/capacity?${new URLSearchParams({company: companyId, ...(leaf ? {category: leaf} : {}), ...(value ? {unit: value.unit} : {})})}`;
  return <div className="offer-resource seller-offer__wide" role="region" aria-label="Проверка доступного ресурса">
    <div className="offer-resource__heading"><strong>{kind === "stock" ? "Свободный остаток склада" : "Свободная мощность на срок"}</strong><button type="button" className="btn btn-secondary btn-sm" onClick={() => setRetry(n => n + 1)}>Обновить ресурс</button></div>
    {error ? <p className="alert alert-error">{error}</p> : !value ? <p role="status">Проверяем ресурс…</p> : <>
      <p className="offer-resource__amount">{formatUnits(value.free_units, value.unit)}{kind === "capacity" && <span> до {formatDate(value.deadline_date)}</span>}</p>
      {kind === "stock" && <p className="hint">Остаток обновлён: {formatDateTime(value.stock_updated_at)}. Подтверждение действует не более 7 дней.</p>}
      {!!value.blockers.length && <p className="alert alert-error">{value.blockers.join(". ")}</p>}
      {units > value.free_units && <p className="alert alert-error">Не хватает {formatUnits(units - value.free_units, value.unit)}. Уменьшите объём предложения или обновите ресурс.</p>}
    </>}
    <Link className="text-link" href={destination}>{kind === "stock" ? "Обновить наличие товара" : "Календарь мощностей"} →</Link>
  </div>;
}

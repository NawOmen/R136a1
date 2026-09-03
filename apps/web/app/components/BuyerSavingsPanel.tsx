"use client";

import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { BuyerSavings, formatRub, marketplace } from "../lib/marketplace";

export function BuyerSavingsPanel({ companyId }: { companyId?: string }) {
  const [value, setValue] = useState<BuyerSavings | null>(null);
  useEffect(() => { const token = getToken(); if (token && companyId) void marketplace.getBuyerSavings(token, companyId).then(setValue).catch(() => setValue(null)); }, [companyId]);
  if (!companyId || !value) return null;
  return <section className="card"><h2>Экономия на коалициях</h2><div className="stats-grid buyer-stats"><article><b>{formatRub(value.confirmed_savings_rub)}</b><span>подтверждено</span></article><article><b>{formatRub(value.calculated_variants_rub)}</b><span>в рассчитанных вариантах</span></article><article><b>{value.coalitions_count}</b><span>коалиций</span></article></div><p className="hint">{value.explanation}</p></section>;
}

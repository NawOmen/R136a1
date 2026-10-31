import type { Money, Offer } from "./marketplace";
import { scaledMoney } from "./money";

/** Show the server's priced volume; never reconstruct a tiered quote with floats. */
export function supplierQuote(offer: Offer | null, need: {id: string; revision: number; volume_units: number} | null): {unitPrice: Money; goodsTotal: Money} | null {
  const quote = offer?.commercial_quote;
  if (!offer || !need || !quote || quote.need?.id !== need.id || quote.need.revision !== need.revision
      || quote.need.units !== need.volume_units || quote.offer?.id !== offer.id || quote.offer.revision !== offer.revision
      || !quote.estimate?.lines) return null;
  const price = quote.estimate.unit_price_rub;
  const goods = quote.estimate.lines.find(line => line.code === "goods" && !line.conditional)?.amount_rub;
  if (price == null || goods == null) return null;
  try {
    if (scaledMoney(price) <= BigInt(0) || scaledMoney(goods) < BigInt(0)) return null;
  } catch { return null; }
  return {unitPrice: price, goodsTotal: goods};
}

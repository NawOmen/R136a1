import type { Product } from "./marketplace";
import { scaledMoney } from "./money";

/** Lowest advertised tier, retaining decimal precision and its actual threshold. */
export function startingPrice(product: Pick<Product, "price_rub" | "price_tiers" | "moq_units">) {
  return (product.price_tiers ?? []).reduce((best, tier) => scaledMoney(tier.unit_price_rub) < scaledMoney(best.price)
    ? { price: tier.unit_price_rub, minUnits: Math.max(product.moq_units, tier.min_units) } : best,
  { price: product.price_rub, minUnits: product.moq_units });
}

/** Seller-reported warehouse stock; actual unreserved volume is checked by the server. */
export function productAvailability(product: Pick<Product, "stock_units" | "stock_updated_at">, now = Date.now()) {
  const updated = product.stock_updated_at ? Date.parse(product.stock_updated_at) : NaN;
  const fresh = Number.isFinite(updated) && updated <= now + 60_000 && updated >= now - 7 * 86_400_000;
  if (product.stock_units == null || !fresh) return { available: false, label: "Уточнить наличие" };
  return product.stock_units > 0 ? { available: true, label: "В наличии" } : { available: false, label: "Под заказ" };
}

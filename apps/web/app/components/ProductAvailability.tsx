import type { Product } from "../lib/marketplace";

export function ProductAvailability({ product }: { product: Pick<Product, "available_stock_units" | "moq_units"> }) {
  const available = product.available_stock_units;
  const known = available !== null && available !== undefined;
  const stocked = known && available >= product.moq_units;
  const label = !known ? "Наличие уточняется" : stocked ? "В наличии" : "Под заказ";
  return <span className={`product-availability ${stocked ? "product-availability--stock" : "product-availability--request"}`} title={stocked ? "Свободного остатка хватает на минимальный заказ. Наличие повторно проверяется при согласовании." : !known ? "Продавцу нужно подтвердить актуальный остаток." : "Свободного остатка недостаточно на минимальную партию. Уточните срок изготовления."}>
    {stocked ? <span className="product-availability__dot" aria-hidden="true" /> : <svg viewBox="0 0 20 20" width="15" height="15" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" /><path d="M10 5v5l3 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>}{label}
  </span>;
}

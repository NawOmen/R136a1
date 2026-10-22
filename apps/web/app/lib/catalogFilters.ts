import { itemUnit, type Product } from "./marketplace";
import { productAvailability, startingPrice } from "./catalogPresentation";
import { scaledMoney } from "./money";

export const catalogSorts = ["popular", "name", "price-asc", "price-desc", "lead-time", "moq"] as const;
export type CatalogSort = typeof catalogSorts[number];
export type CatalogFilters = {
  priceFrom: string;
  priceTo: string;
  inStock: boolean;
  leadDays: string;
  moq: string;
  subcategory: string;
  unit: string;
};
export type CatalogFilterErrors = Partial<Record<"priceFrom" | "priceTo" | "leadDays" | "moq", string>>;
export const emptyCatalogFilters: CatalogFilters = { priceFrom: "", priceTo: "", inStock: false, leadDays: "", moq: "", subcategory: "", unit: "" };

export function validateCatalogFilters(input: CatalogFilters): { filters: CatalogFilters; errors: CatalogFilterErrors } {
  const filters = { ...input, priceFrom: input.priceFrom.trim().replace(",", "."), priceTo: input.priceTo.trim().replace(",", "."), leadDays: input.leadDays.trim(), moq: input.moq.trim() };
  const errors: CatalogFilterErrors = {};
  for (const field of ["priceFrom", "priceTo"] as const) {
    if (filters[field] && !/^\d+(?:\.\d{1,12})?$/.test(filters[field])) errors[field] = "Введите цену от 0 ₽, до 12 знаков после запятой.";
  }
  if (!errors.priceFrom && !errors.priceTo && filters.priceFrom && filters.priceTo && scaledMoney(filters.priceFrom) > scaledMoney(filters.priceTo)) errors.priceTo = "Цена до должна быть не меньше цены от.";
  if (filters.leadDays && (!/^\d+$/.test(filters.leadDays) || !Number.isSafeInteger(Number(filters.leadDays)))) errors.leadDays = "Введите целое число дней от 0.";
  if (filters.moq && (!/^\d+$/.test(filters.moq) || !Number.isSafeInteger(Number(filters.moq)) || Number(filters.moq) < 1)) errors.moq = "Введите целое число единиц от 1.";
  return { filters, errors };
}

export function activeCatalogFilterCount(filters: CatalogFilters): number {
  return Object.values(filters).filter(Boolean).length;
}

export function readCatalogLocation(search: string) {
  const params = new URLSearchParams(search), candidate = params.get("sort");
  const sort: CatalogSort = catalogSorts.includes(candidate as CatalogSort) ? candidate as CatalogSort : "popular";
  return {
    query: params.get("q") ?? "", category: params.get("category") ?? "", sort,
    filters: { priceFrom: params.get("price_from") ?? "", priceTo: params.get("price_to") ?? "", inStock: params.get("in_stock") === "1", leadDays: params.get("lead_days") ?? "", moq: params.get("moq") ?? "", subcategory: params.get("subcategory") ?? "", unit: params.get("unit") ?? "" },
  };
}

export function writeCatalogLocation(search: string, state: { query: string; category: string; sort: CatalogSort; filters: CatalogFilters }): string {
  const params = new URLSearchParams(search);
  const values = { q: state.query, category: state.category, sort: state.sort === "popular" ? "" : state.sort, price_from: state.filters.priceFrom, price_to: state.filters.priceTo, in_stock: state.filters.inStock ? "1" : "", lead_days: state.filters.leadDays, moq: state.filters.moq, subcategory: state.filters.subcategory, unit: state.filters.unit };
  for (const [key, value] of Object.entries(values)) { if (value) params.set(key, value); else params.delete(key); }
  return params.toString();
}

function knownNonnegative(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value) && value >= 0; }
function ascendingKnown(a: unknown, b: unknown, positive = false): number {
  const av = knownNonnegative(a) && (!positive || a > 0) ? a : Infinity;
  const bv = knownNonnegative(b) && (!positive || b > 0) ? b : Infinity;
  return av === bv ? 0 : av < bv ? -1 : 1;
}

/** All client controls operate on the admitted set in the server's popularity order. */
export function filterCatalog(products: Product[], category: string, query: string, sort: CatalogSort, filters: CatalogFilters, now = Date.now()): Product[] {
  const normalized = query.trim().toLocaleLowerCase("ru");
  const minimum = filters.priceFrom ? scaledMoney(filters.priceFrom) : null;
  const maximum = filters.priceTo ? scaledMoney(filters.priceTo) : null;
  const result = products.filter(product => {
    if (category && product.category !== category) return false;
    if (normalized && !`${product.name} ${product.category} ${product.subcategory ?? ""}`.toLocaleLowerCase("ru").includes(normalized)) return false;
    if (filters.subcategory && product.subcategory !== filters.subcategory) return false;
    if (filters.unit && itemUnit(product.characteristics) !== filters.unit) return false;
    if (filters.inStock && !productAvailability(product, now).available) return false;
    if (filters.leadDays && (!knownNonnegative(product.lead_time_days) || product.lead_time_days > Number(filters.leadDays))) return false;
    if (filters.moq && (!knownNonnegative(product.moq_units) || product.moq_units <= 0 || product.moq_units > Number(filters.moq))) return false;
    if (minimum !== null || maximum !== null) {
      const price = scaledMoney(startingPrice(product).price);
      if ((minimum !== null && price < minimum) || (maximum !== null && price > maximum)) return false;
    }
    return true;
  });
  if (sort === "name") result.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  else if (sort === "price-asc" || sort === "price-desc") result.sort((a, b) => {
    const ap = scaledMoney(startingPrice(a).price), bp = scaledMoney(startingPrice(b).price);
    return ap === bp ? 0 : (ap < bp ? -1 : 1) * (sort === "price-desc" ? -1 : 1);
  });
  else if (sort === "lead-time") result.sort((a, b) => ascendingKnown(a.lead_time_days, b.lead_time_days));
  else if (sort === "moq") result.sort((a, b) => ascendingKnown(a.moq_units, b.moq_units, true));
  return result;
}

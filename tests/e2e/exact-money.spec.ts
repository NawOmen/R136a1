import { expect, test } from "@playwright/test";
import { displayMoney, lineAmount, previewLineAmount, scaledMoney, moneyInputValue } from "../../apps/web/app/lib/money";
import { marketplace } from "../../apps/web/app/lib/marketplace";
import type { Product } from "../../apps/web/app/lib/marketplace";
import { emptyCatalogFilters, filterCatalog, readCatalogLocation, validateCatalogFilters, writeCatalogLocation } from "../../apps/web/app/lib/catalogFilters";

test("exact subkopeck prices, large quantities and negative money retain their values", () => {
  expect(lineAmount("0.00000000125", 1_000_000_000)).toBe("1.250000000000");
  expect(lineAmount("7", "2.5")).toBe("17.500000000000");
  expect(lineAmount("0.005",1)).toBe("0.010000000000");
  expect(displayMoney("2.675")).toBe("2,68 ₽");
  expect(displayMoney("-1000.01")).toBe("−1\u00a0000,01 ₽");
  expect(displayMoney("150.123456789012",12)).toBe("150,12 ₽");
  expect(displayMoney("0.00000000125")).toBe("менее 0,01 ₽");
  expect(()=>scaledMoney("NaN")).toThrow();
  expect(previewLineAmount("",1)).toBeNull();
  expect(previewLineAmount("7","2.5")).toBe("17.500000000000");
});

test("marketplace client uses exact v3 without converting submitted prices", async () => {
  const original=globalThis.fetch;
  let url="",body="";
  globalThis.fetch=async (input,init)=> {url=String(input);body=String(init?.body);return Response.json({id:"quote"});};
  try {
    await marketplace.createOffer("synthetic-token","need",{company_id:"seller",price_rub:"0.00000000125",available_units:1000000000,lead_time_days:1,moq_units:1,delivery_cost_rub:null});
    expect(url).toContain("/api/v3/needs/need/offers");
    expect(JSON.parse(body).price_rub).toBe("0.00000000125");
    expect(JSON.parse(body).delivery_cost_rub).toBeNull();
  } finally {globalThis.fetch=original;}
});

test("catalogue price controls compare exact advertised tier prices", () => {
  const make = (id: string, price: string, extra: Partial<Product> = {}) => ({ id, name: id, category: "Упаковка и тара", subcategory: "Коробки", price_rub: price, price_tiers: [], moq_units: 1, lead_time_days: 4, characteristics: { unit: "шт" }, ...extra } as Product);
  const products = [make("high", "1.000000000002"), make("low", "1.000000000001"), make("tier", "3", { price_tiers: [{ min_units: 100, unit_price_rub: "0.999999999999" }] })];
  expect(filterCatalog(products, "", "", "popular", emptyCatalogFilters).map(p => p.id)).toEqual(["high", "low", "tier"]);
  expect(filterCatalog(products, "", "", "price-asc", emptyCatalogFilters).map(p => p.id)).toEqual(["tier", "low", "high"]);
  const checked = validateCatalogFilters({ ...emptyCatalogFilters, priceFrom: "1,000000000002", priceTo: "1.000000000002" });
  expect(checked.errors).toEqual({});
  expect(filterCatalog(products, "", "", "price-desc", checked.filters).map(p => p.id)).toEqual(["high"]);
  expect(filterCatalog(products, "", "", "popular", { ...emptyCatalogFilters, priceTo: "0.999999999999" }).map(p => p.id)).toEqual(["tier"]);
  expect(products.map(p => p.id)).toEqual(["high", "low", "tier"]);
});

test("catalogue availability uses inclusive freshness boundaries and excludes unknown limits", () => {
  const now = Date.parse("2026-10-22T06:00:00Z");
  const make = (id: string, extra: Record<string, unknown> = {}) => ({ id, name: id, category: "Упаковка и тара", price_rub: "5", price_tiers: [], moq_units: 2, lead_time_days: 2, characteristics: {}, stock_units: 10, stock_updated_at: new Date(now).toISOString(), ...extra } as Product);
  const products = [make("fresh"), make("old-boundary", { stock_updated_at: new Date(now - 7 * 86_400_000).toISOString() }), make("future-boundary", { stock_updated_at: new Date(now + 60_000).toISOString() }), make("stale", { stock_updated_at: new Date(now - 7 * 86_400_000 - 1).toISOString() }), make("future", { stock_updated_at: new Date(now + 60_001).toISOString() }), make("unknown", { stock_units: null }), make("missing-lead", { lead_time_days: undefined }), make("missing-moq", { moq_units: undefined })];
  const filters = { ...emptyCatalogFilters, inStock: true, leadDays: "2", moq: "2" };
  expect(filterCatalog(products, "", "", "popular", filters, now).map(p => p.id)).toEqual(["fresh", "old-boundary", "future-boundary"]);
  expect(filterCatalog(products, "", "", "lead-time", emptyCatalogFilters, now).at(-1)?.id).toBe("missing-lead");
  expect(filterCatalog(products, "", "", "moq", emptyCatalogFilters, now).at(-1)?.id).toBe("missing-moq");
});

test("catalogue validation rejects invalid ranges and URL state retains the search", () => {
  for (const value of ["-1", "сумма", "1.0000000000001", "Infinity", "1e3"]) expect(validateCatalogFilters({ ...emptyCatalogFilters, priceFrom: value }).errors.priceFrom).toBeTruthy();
  expect(validateCatalogFilters({ ...emptyCatalogFilters, priceFrom: "2", priceTo: "1" }).errors.priceTo).toBeTruthy();
  expect(validateCatalogFilters({ ...emptyCatalogFilters, leadDays: "-1" }).errors.leadDays).toBeTruthy();
  expect(validateCatalogFilters({ ...emptyCatalogFilters, moq: "заказ" }).errors.moq).toBeTruthy();
  const state = { query: "коробка", category: "Упаковка и тара", sort: "price-asc" as const, filters: { ...emptyCatalogFilters, priceFrom: "1.000000000001", inStock: true, unit: "шт." } };
  const encoded = writeCatalogLocation("?q=коробка", state);
  expect(readCatalogLocation(encoded)).toEqual(state);
  const reset = writeCatalogLocation(encoded, { ...state, category: "", filters: emptyCatalogFilters });
  expect(new URLSearchParams(reset).get("q")).toBe("коробка");
  expect(new URLSearchParams(reset).has("price_from")).toBe(false);
  expect(readCatalogLocation("?sort=not-a-sort").sort).toBe("popular");
});


test("new money input rounds decimal strings to kopecks without losing large integer digits", () => {
  for (const [input, expected] of [
    ["", ""], ["1.", "1."], ["1.20", "1.20"], ["1,25", "1.25"],
    ["2.675", "2.68"], ["4.123456789012", "4.12"], ["9.999", "10.00"],
    ["0.005", "0.01"], ["-2.675", "-2.68"],
    ["9007199254740993.995", "9007199254740994.00"],
  ]) expect(moneyInputValue(input)).toBe(expected);
  expect(moneyInputValue(null)).toBe("");
  // Formatting a copy must not mutate a saved price or change exact API arithmetic.
  const original = "4.123456789012";
  expect(moneyInputValue(original)).toBe("4.12");
  expect(scaledMoney(original)).toBe(BigInt("4123456789012"));
});

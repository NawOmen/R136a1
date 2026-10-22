import { expect, test } from "@playwright/test";
import { formatDate, formatDateTime, parseDateInput } from "../../apps/web/app/lib/dates";
import { displayValue, russianLabel } from "../../apps/web/app/lib/presentation";
import { startingPrice, productAvailability } from "../../apps/web/app/lib/catalogPresentation";
import { formatUnits, itemUnit } from "../../apps/web/app/lib/marketplace";

test("Russian calendar dates validate leap days without time-zone shifts or API changes", () => {
  expect(formatDate("2026-10-20")).toBe("20.10.26");
  expect(formatDate("2024-02-29")).toBe("29.02.24");
  expect(formatDate("2026-02-29")).toBe("—");
  expect(formatDate("2026-13-20")).toBe("—");
  expect(formatDateTime("not a date")).toBe("—");
  expect(formatDateTime("2026-10-20T12:05:00Z")).toMatch(/^20\.10\.26, \d{2}:\d{2}$/);
  for (const timestamp of ["2026-10-20T00:30:00+14:00", "2026-10-20T23:30:00-12:00"]) {
    expect(formatDate(timestamp)).toBe(formatDateTime(timestamp).split(",")[0]);
  }
  expect(parseDateInput("29.02.24")).toBe("2024-02-29");
  expect(parseDateInput("29.02.26")).toBe("");
  expect(parseDateInput("31.12.2026")).toBe("2026-12-31");
  expect(displayValue({ deadline_date: "2026-11-20", source: "rules_only" })).toBe("Срок поставки: 20.11.26; Источник: Программные правила");
  expect(russianLabel("includes_vat")).toBe("С НДС");
  expect(itemUnit({ unit: "pcs" })).toBe("шт.");
});

test("catalogue package quantities use Russian count forms without changing units", () => {
  for (const [quantity, label] of [[1, "рулон"], [2, "рулона"], [5, "рулонов"], [11, "рулонов"], [21, "рулон"]] as const) {
    expect(formatUnits(quantity, "roll")).toBe(`${quantity} ${label}`);
  }
  expect(formatUnits(2, "бухта")).toBe("2 бухты");
  expect(formatUnits(20, "упаковка")).toBe("20 упаковок");
  expect(formatUnits(100, "шт.")).toBe("100 шт.");
  expect(formatUnits(10, "кг")).toBe("10 кг");
  expect(itemUnit({ unit: "бухта" })).toBe("бухта");
});

test("catalogue starting price preserves exact decimals and its tier quantity", () => {
  expect(startingPrice({ price_rub: "38.123456789124", moq_units: 100, price_tiers: [{ min_units: 1000, unit_price_rub: "38.123456789123" }] })).toEqual({ price: "38.123456789123", minUnits: 1000 });
  expect(startingPrice({ price_rub: "7", moq_units: 100, price_tiers: [] })).toEqual({ price: "7", minUnits: 100 });
});

test("availability needs fresh seller stock, not publication or verification", () => {
  const now = Date.parse("2026-10-20T10:00:00Z");
  expect(productAvailability({ stock_units: 10, stock_updated_at: "2026-10-20T09:00:00Z" }, now).label).toBe("В наличии");
  expect(productAvailability({ stock_units: 0, stock_updated_at: "2026-10-20T09:00:00Z" }, now).label).toBe("Под заказ");
  for (const updated of [null, "invalid", "2026-10-12T09:00:00Z", "2026-11-20T09:00:00Z"]) {
    expect(productAvailability({ stock_units: 10, stock_updated_at: updated }, now).label).toBe("Уточнить наличие");
  }
  expect(productAvailability({ stock_units: null, stock_updated_at: "2026-10-20T09:00:00Z" }, now).available).toBe(false);
});

import { expect, test } from "@playwright/test";
import { characteristicField, characteristicSuggestions, categoryProfile, registryCharacteristicLabel } from "../../apps/web/app/lib/categoryProfiles";

test("category choices use their own fields and avoid existing aliases", () => {
  const packaging = characteristicSuggestions("Упаковка и тара", "Бумажные стаканы", [" Материал ", "объём"]);
  expect(packaging.some((field) => field.key === "material" || field.key === "volume_ml")).toBe(false);
  const furniture = characteristicSuggestions("Товары для бизнеса", "Мебель", []);
  expect(furniture.some((field) => field.key === "volume_ml")).toBe(false);
  expect(furniture.some((field) => field.key === "dimensions_mm")).toBe(true);
  expect(characteristicSuggestions("Услуги производства", "Сборка", []).some((field) => field.key === "output")).toBe(true);
});

test("empty or unknown classification does not invent a profile", () => {
  expect(characteristicSuggestions("Строительство", "", [])).toEqual([]);
  expect(categoryProfile("Строительство", "Неизвестно")).toBeUndefined();
});

test("labels and numeric input metadata resolve aliases without changing user values", () => {
  expect(characteristicField("Упаковка и тара", "Бумажные стаканы", "ОБЪЕМ")?.unit).toBe("мл");
  expect(characteristicField("Строительство", "Крепёж", "length_mm")?.type).toBe("number");
  expect(registryCharacteristicLabel("power_kw")).toBe("Мощность, кВт");
  expect(characteristicField("Товары для бизнеса", "Мебель", "dimensions_mm")?.type).toBe("text");
  expect(characteristicField("Товары для бизнеса", "Мебель", "параметр пользователя")).toBeUndefined();
});

test("generic dimensions do not imply millimetres or hide an explicit dimension field", async () => {
  const { formatCharacteristics } = await import("../../apps/web/app/lib/marketplace");
  expect(formatCharacteristics({ dimensions: "120×60×75 см" })).toBe("Габариты: 120×60×75 см");
  expect(formatCharacteristics({ dimensions_mm: "1200×600×750" })).toBe("Габариты, мм: 1200×600×750");
  expect(characteristicField("Товары для бизнеса", "Мебель", "dimensions")).toBeUndefined();
  expect(characteristicSuggestions("Товары для бизнеса", "Мебель", ["dimensions"])
    .some((field) => field.key === "dimensions_mm")).toBe(true);
  expect(characteristicSuggestions("Товары для бизнеса", "Мебель", ["dimensions_mm"])
    .some((field) => field.key === "dimensions_mm")).toBe(false);
});


test("saved technical labels remain tied to their captured profile", async () => {
  const { formatCharacteristics } = await import("../../apps/web/app/lib/marketplace");
  const profile = {
    snapshot_version: 1, registry_version: "previous", category_id: "test", leaf_revision: 1,
    profile_version: 1, state: "initial", required_for_product: [],
    fields: { length_mm: { label: "Сохранённая длина, мм", type: "number" as const, aliases: ["длина"] } },
  };
  expect(formatCharacteristics({ length_mm: 12, " ДЛИНА ": "15 мм", custom: "значение" }, profile))
    .toBe("Сохранённая длина, мм: 12 · Сохранённая длина, мм: 15 мм · custom: значение");
  expect(formatCharacteristics({ length_mm: 12 }, null)).toBe("Длина, мм: 12");
});

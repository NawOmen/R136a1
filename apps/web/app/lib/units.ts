/** Display aliases only; stored units and API values are unchanged. */
export function russianUnit(value: string | null | undefined): string {
  const units: Record<string, string> = { unit: "шт.", units: "шт.", piece: "шт.", pieces: "шт.", pc: "шт.", pcs: "шт.", kg: "кг", kilogram: "кг", kilograms: "кг", mg: "мг", mm: "мм", cm: "см", dm: "дм", km: "км", "m^2": "м²", "m^3": "м³", hour: "ч", day: "дн.", g: "г", t: "т", ton: "т", tonne: "т", l: "л", liter: "л", litre: "л", ml: "мл", m: "м", meter: "м", metre: "м", m2: "м²", "m²": "м²", m3: "м³", "m³": "м³", roll: "рулон", pack: "упак.", package: "упак.", box: "коробка", set: "комплект" };
  return value ? units[value.trim().toLowerCase()] ?? value : "";
}

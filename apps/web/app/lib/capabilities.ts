import type { CapabilityDetails } from "./marketplace";

export const EMPTY_CAPABILITY_DETAILS: CapabilityDetails = {
  business_kind: "manufacturer", product_types: "", complexity: "", material_grades: "",
  limitations: "", packaging: "", delivery: "", quality_control: "", trial_batch: "",
};

export const CAPABILITY_FIELDS = [
  { key: "product_types", label: "Что производите или поставляете", max: 1200, example: "Валы, втулки, фланцы по чертежам" },
  { key: "complexity", label: "Сложность и операции", max: 1200, example: "Токарная обработка, фрезеровка; 3-осевые детали" },
  { key: "material_grades", label: "Марки и разновидности материалов", max: 800, example: "Сталь 45, алюминий АМг6" },
  { key: "limitations", label: "Ограничения и исключения", max: 1200, example: "Без термообработки; сложные полости — после проверки чертежа" },
  { key: "packaging", label: "Упаковка", max: 800, example: "Короба по 500 шт., паллетирование" },
  { key: "delivery", label: "Условия отгрузки и доставки", max: 800, example: "Самовывоз или передача перевозчику покупателя" },
  { key: "quality_control", label: "Контроль качества", max: 800, example: "Проверка размеров, протокол контроля партии" },
  { key: "trial_batch", label: "Пробная партия", max: 800, example: "От 10 шт.; цена и срок после согласования" },
] as const;

export function parseSizeRanges(value: string): Record<string, [number, number]> {
  const result: Record<string, [number, number]> = {};
  for (const line of value.split("\n").filter((item) => item.trim())) {
    const parts = line.split(":").map((item) => item.trim());
    const [key, low, high] = parts;
    const min = Number(low), max = Number(high);
    if (parts.length !== 3 || !key || !low || !high || !Number.isFinite(min) || !Number.isFinite(max) || min < 0 || max < min || Object.hasOwn(result, key)) {
      throw new Error("Размеры: укажите уникальное название с единицей, минимум и максимум через двоеточие.");
    }
    Object.defineProperty(result, key, { value: [min, max], enumerable: true });
  }
  return result;
}

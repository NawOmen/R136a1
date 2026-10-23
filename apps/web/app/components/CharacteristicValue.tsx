"use client";
import { categoryProfile, characteristicField } from "../lib/categoryProfiles";
const allUnits = ["шт", "кг", "г", "т", "м", "мм", "м²", "см²", "м³", "л", "мл", "упак", "комплект", "рулон", "мешок", "бухта", "час", "мин"];
export function CharacteristicValue({ category, subcategory, fieldKey, value, onChange, label }: { category: string; subcategory: string; fieldKey: string; value: string; onChange: (value: string) => void; label: string }) {
  const profile = categoryProfile(category, subcategory) as { passport?: { units?: { allowed?: string[] } } } | undefined;
  const units = profile?.passport?.units?.allowed ?? allUnits;
  const field = characteristicField(category, subcategory, fieldKey);
  if (["unit", "единица измерения"].includes(fieldKey.trim().toLowerCase())) return <select aria-label={label} value={units.includes(value) ? value : ""} required onChange={e=>onChange(e.target.value)}><option value="" disabled>Выберите единицу</option>{units.map(u=><option key={u}>{u}</option>)}</select>;
  const numeric = field?.type === "number" || field?.type === "integer";
  return <div className="characteristic-value"><input type="text" inputMode={numeric ? "decimal" : "text"} placeholder={numeric ? "Количество" : "Значение"} aria-label={`${label}${field?.unit ? `, ${field.unit}` : ""}`} required value={value} onChange={e=>onChange(e.target.value)} />{field?.unit && <span>{field.unit}</span>}</div>;
}

import registry from "./category-registry.generated.json";

type TechnicalProfile = { version: number; state: string; fields: string[]; required_for_product: string[] };
export type CharacteristicField = { label: string; type: string; aliases: string[]; unit?: string; positive?: boolean };
const profiles: Record<string, TechnicalProfile> = registry.technical_profiles;
const fields: Record<string, CharacteristicField> = registry.characteristic_fields;
const ids: Record<string, Record<string, string>> = registry.leaf_ids;
const normalize = (value: string) => value.trim().toLowerCase().replaceAll("ё", "е");

export function categoryProfile(category: string, subcategory: string): TechnicalProfile | undefined {
  return profiles[ids[category]?.[subcategory] ?? ""];
}

export function characteristicField(category: string, subcategory: string, key: string): CharacteristicField | undefined {
  const profile = categoryProfile(category, subcategory);
  return profile?.fields.map((name) => fields[name]).find((field, index) =>
    [profile.fields[index], ...field.aliases].some((alias) => normalize(alias) === normalize(key)));
}

export function characteristicSuggestions(category: string, subcategory: string, existingKeys: string[]) {
  const profile = categoryProfile(category, subcategory);
  if (!profile) return [];
  const present = new Set(existingKeys.map(normalize));
  return profile.fields.filter((key) => ![key, ...fields[key].aliases].some((alias) => present.has(normalize(alias))))
    .map((key) => ({ key, ...fields[key], required: profile.required_for_product.includes(key) }));
}

export function registryCharacteristicLabel(key: string): string | undefined {
  return Object.entries(fields).find(([name, field]) => [name, ...field.aliases].some((alias) => normalize(alias) === normalize(key)))?.[1].label;
}

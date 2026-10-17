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

const SYSTEM_KEYS = new Set(["unit", "единица измерения"]);

/** Нормализованные ключи системных и обязательных свойств: вне лимита 25 пользовательских. */
export function requiredCharacteristicKeys(category: string, subcategory: string): Set<string> {
  const profile = categoryProfile(category, subcategory);
  const keys = new Set(SYSTEM_KEYS);
  for (const name of profile?.required_for_product ?? []) {
    keys.add(normalize(name));
    for (const alias of fields[name]?.aliases ?? []) keys.add(normalize(alias));
  }
  const identification = (profile as unknown as { passport?: { identification?: { required_when?: { required?: string[] }[] } } })?.passport?.identification;
  for (const rule of identification?.required_when ?? []) {
    for (const name of rule.required ?? []) {
      keys.add(normalize(name));
      for (const alias of fields[name]?.aliases ?? []) keys.add(normalize(alias));
    }
  }
  return keys;
}

export function countUserCharacteristics(rows: { key: string }[], category: string, subcategory: string): number {
  const skip = requiredCharacteristicKeys(category, subcategory);
  return rows.filter((row) => !skip.has(normalize(row.key))).length;
}

/** Exact catalogue names/IDs and a small unambiguous product vocabulary.
 * A broad parent never silently picks its first child or becomes Other.
 */
export function resolveAgentCategory(category: string, productType = ""): { category: string; subcategory: string } | null {
  const aliases: Record<string, string> = {
    "упаковка": "Упаковка и тара", "тара": "Упаковка и тара",
    "гофрокороб": "Коробки", "гофрокороба": "Коробки", "гофрокоробки": "Коробки",
    "коробка": "Коробки", "картонные коробки": "Коробки",
    "бумажные стаканчики": "Бумажные стаканы", "крафтовые стаканы": "Бумажные стаканы",
  };
  function resolve(raw: string) {
    const value = normalize(aliases[normalize(raw)] ?? raw);
    for (const [parent, leaves] of Object.entries(ids)) {
      for (const [label, id] of Object.entries(leaves)) {
        if ([label, id].some(item => normalize(item) === value)) return { category: parent, subcategory: label };
      }
      if (normalize(parent) === value) return { category: parent, subcategory: "" };
    }
    return null;
  }
  const detected = resolve(category);
  const product = resolve(productType);
  if (detected?.subcategory) return detected;
  if (product?.subcategory && (!detected || detected.category === product.category)) return product;
  return detected;
}

/** Russian input labels and legacy aliases serialize to stable API keys. */
export function canonicalCharacteristicKey(value: string): string {
  const wanted = normalize(value);
  return Object.entries(fields).find(([name, field]) => [name, field.label, ...field.aliases].some(alias => normalize(alias) === wanted))?.[0] ?? value;
}

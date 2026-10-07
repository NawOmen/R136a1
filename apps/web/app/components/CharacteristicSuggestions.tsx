"use client";

import { characteristicSuggestions } from "../lib/categoryProfiles";

export default function CharacteristicSuggestions({ category, subcategory, keys, onAdd, disabled = false, product = false }: {
  category: string; subcategory: string; keys: string[]; onAdd: (key: string) => void; disabled?: boolean; product?: boolean;
}) {
  const suggestions = characteristicSuggestions(category, subcategory, keys);
  if (!suggestions.length) return null;
  return (
    <>
      <select aria-label="Добавить характеристику категории" value="" disabled={disabled || keys.length >= 25}
        onChange={(event) => { if (event.target.value) onAdd(event.target.value); }}>
        <option value="">Добавить поле для этой категории</option>
        {suggestions.map((field) => <option key={field.key} value={field.key}>
          {field.label}{product && field.required ? " — обязательно для публикации" : ""}
        </option>)}
      </select>
      <p className="hint">Поля соответствуют выбранной подкатегории. Дополнительные характеристики можно указать вручную.</p>
    </>
  );
}

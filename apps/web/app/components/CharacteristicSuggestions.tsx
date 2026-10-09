"use client";

import { useEffect, useState } from "react";
import { marketplace, EditorRegistry } from "../lib/marketplace";
import { countUserCharacteristics, requiredCharacteristicKeys } from "../lib/categoryProfiles";

export default function CharacteristicSuggestions({ category, subcategory, keys, onAdd, disabled = false, product = false }: {
  category: string; subcategory: string; keys: string[]; onAdd: (key: string) => void; disabled?: boolean; product?: boolean;
}) {
  const [registry,setRegistry]=useState<EditorRegistry["registry"]|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [limitMessage,setLimitMessage]=useState<string|null>(null);
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    let active=true; setError(null);
    marketplace.getCategoryRegistry().then(data=>{if(active)setRegistry(data);}).catch(err=>{if(active)setError(err instanceof Error?err.message:"Не удалось загрузить правила.");});
    return()=>{active=false;};
  },[retry]);
  if(error)return <p role="alert" className="hint">{error} <button type="button" onClick={()=>setRetry(value=>value+1)}>Повторить загрузку правил</button></p>;
  if(!registry)return <p role="status" className="hint">Загрузка полей категории…</p>;
  const profile=registry.groups.find(group=>group.label===category)?.leaves.find(leaf=>leaf.label===subcategory)?.technical_profile;
  const normalize=(value:string)=>value.trim().toLowerCase().replaceAll("ё","е");
  const present=new Set(keys.map(normalize));
  const requiredKeys = requiredCharacteristicKeys(category, subcategory);
  const suggestions=(profile?.fields ?? []).filter(key=>![key,...registry.characteristic_fields[key].aliases].some(alias=>present.has(normalize(alias))))
    .map(key=>({key,...registry.characteristic_fields[key],required:profile?.required_for_product.includes(key),outsideLimit:requiredKeys.has(normalize(key))}));
  if (!suggestions.length) return null;
  const full = countUserCharacteristics(keys.map((key) => ({ key })), category, subcategory) >= 25;
  return (
    <>
      <select aria-label="Добавить характеристику категории" value="" disabled={disabled}
        onChange={(event) => {
          if (!event.target.value) return;
          const picked = suggestions.find((field) => field.key === event.target.value);
          if (full && !picked?.outsideLimit) {
            setLimitMessage("Лимит 25 пользовательских исчерпан: можно добавить только обязательные для публикации поля.");
            return;
          }
          setLimitMessage(null);
          onAdd(event.target.value);
        }}>
        <option value="">Добавить поле для этой категории</option>
        {suggestions.map((field) => <option key={field.key} value={field.key}>
          {field.label}{product && field.required ? " — обязательно для публикации" : ""}
        </option>)}
      </select>
      <p className="hint">Поля соответствуют выбранной подкатегории. Дополнительные характеристики можно указать вручную.</p>
      {limitMessage && <p role="alert" className="hint">{limitMessage}</p>}
    </>
  );
}

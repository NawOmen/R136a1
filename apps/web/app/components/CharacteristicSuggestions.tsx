"use client";

import { useEffect, useState } from "react";
import { marketplace, EditorRegistry } from "../lib/marketplace";

export default function CharacteristicSuggestions({ category, subcategory, keys, onAdd, disabled = false, product = false }: {
  category: string; subcategory: string; keys: string[]; onAdd: (key: string) => void; disabled?: boolean; product?: boolean;
}) {
  const [registry,setRegistry]=useState<EditorRegistry["registry"]|null>(null);
  const [error,setError]=useState<string|null>(null);
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
  const suggestions=(profile?.fields ?? []).filter(key=>![key,...registry.characteristic_fields[key].aliases].some(alias=>present.has(normalize(alias))))
    .map(key=>({key,...registry.characteristic_fields[key],required:profile?.required_for_product.includes(key)}));
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

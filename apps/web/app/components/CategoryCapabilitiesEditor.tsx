"use client";
import { useEffect, useState } from "react";
import { CategoryCapability, EditorRegistry, marketplace } from "../lib/marketplace";

export default function CategoryCapabilitiesEditor({value,onChange,disabled=false}:{value:CategoryCapability[];onChange:(value:CategoryCapability[])=>void;disabled?:boolean}) {
  const [registry,setRegistry]=useState<EditorRegistry["registry"]|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [retry,setRetry]=useState(0);
  const [extraKeys,setExtraKeys]=useState<Record<number,string>>({});
  useEffect(()=>{let active=true;marketplace.getCategoryRegistry().then(data=>{if(active){setRegistry(data);setError(null);}}).catch(err=>{if(active)setError(err instanceof Error?err.message:"Не удалось загрузить правила категорий.");});return()=>{active=false;};},[retry]);
  const leaves=registry?.groups.flatMap(group=>group.leaves.filter(leaf=>leaf.admission_state!=="unsupported").map(leaf=>({...leaf,title:group.label+" / "+leaf.label}))) ?? [];
  function update(index:number,patch:Partial<CategoryCapability>){onChange(value.map((scope,i)=>i===index?{...scope,...patch}:scope));}
  return <fieldset disabled={disabled}><legend>Возможности по подкатегориям</legend>
    <p className="hint">Каждая подкатегория имеет свою единицу, минимальный и максимальный заказ и допустимые свойства. Это заявление продавца; документы и свободный ресурс проверяются отдельно. При сохранении фиксируется текущая версия правил. Физические объёмы задавайте в единице хранения: г, мм, см² или мл; MOQ и предел — целое число таких единиц. Например 2,5 кг — 2500 г.</p>
    {error && <p role="alert">{error} <button type="button" onClick={()=>setRetry(v=>v+1)}>Повторить</button></p>}
    {value.map((scope,index)=><div className="card" key={index}>
      <label>Подкатегория<select required value={scope.category_id} onChange={event=>update(index,{category_id:event.target.value,characteristics:{}})}><option value="">Выберите</option>{leaves.map(leaf=><option key={leaf.id} value={leaf.id}>{leaf.title}</option>)}</select></label>
      <label>Единица заказа<input required value={scope.unit} onChange={event=>update(index,{unit:event.target.value})} /></label>
      <label>Минимальный заказ<input type="number" min={1} step={1} required value={scope.min_units} onChange={event=>update(index,{min_units:Number(event.target.value)})} /></label>
      <label>Максимальный заказ, если ограничен<input type="number" min={scope.min_units} step={1} value={scope.max_units ?? ""} onChange={event=>update(index,{max_units:event.target.value?Number(event.target.value):null})} /></label>
      <p className="hint">Допустимые значения свойств задаются отдельно. Неуказанное свойство не означает подтверждённую возможность.</p>
      {Array.from(new Set([...(leaves.find(leaf=>leaf.id===scope.category_id)?.technical_profile.fields ?? []),...Object.keys(scope.characteristics)])).filter(key=>key!=="unit").map(key=><label key={key}>{registry?.characteristic_fields[key]?.label ?? key}<input value={(scope.characteristics[key] ?? []).map(value=>typeof value==="string"?value:JSON.stringify(value)).join(" | ")} placeholder="Допустимые значения через |" onChange={event=>{const chars={...scope.characteristics};const options=event.target.value.split("|").map(v=>v.trim()).filter(Boolean);if(options.length)chars[key]=options.map(value=>{if(value==="true")return true;if(value==="false")return false;return value;});else delete chars[key];update(index,{characteristics:chars});}} /></label>)}
      <label>Дополнительное свойство<input value={extraKeys[index] ?? ""} placeholder="Например food_contact" onChange={event=>setExtraKeys({...extraKeys,[index]:event.target.value})} /></label>
      <button type="button" disabled={!extraKeys[index]?.trim() || extraKeys[index].trim()==="unit"} onClick={()=>{const key=extraKeys[index].trim();if(!(key in scope.characteristics))update(index,{characteristics:{...scope.characteristics,[key]:[]}});setExtraKeys({...extraKeys,[index]:""});}}>Добавить свойство</button>
      <p className="hint">Для логических признаков используйте true или false. Дополнительное свойство нужно подтвердить применимыми документами; само заявление не даёт допуска.</p>
      {!!scope.profile_version && <p className="hint">Сохранённая версия профиля: {scope.profile_version}</p>}
      <button type="button" onClick={()=>onChange(value.filter((_,i)=>i!==index))}>Удалить область</button>
    </div>)}
    <button type="button" disabled={!registry} onClick={()=>onChange([...value,{category_id:"",unit:"шт",characteristics:{},min_units:1,max_units:null,profile_version:0}])}>Добавить подкатегорию</button>
  </fieldset>;
}

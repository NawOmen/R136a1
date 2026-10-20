"use client";
import { russianUnit } from "../lib/units";
import { russianMessage } from "../lib/russianMessages";
import { useEffect, useState } from "react";
import {getToken} from "../lib/api";
import {marketplace,PackagingDefinition,Product} from "../lib/marketplace";
export default function PackagingConversionPanel({product,onSaved}:{product:Product;onSaved:()=>Promise<void>}){
  const [target,setTarget]=useState(product.quantity_conversion?.to_unit ?? "шт");
  const [factor,setFactor]=useState(String(product.quantity_conversion?.factor ?? ""));
  const [preview,setPreview]=useState<PackagingDefinition|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const specification = JSON.stringify([product.characteristics,product.category_profile]);
  useEffect(()=>{setPreview(null);},[specification]);
  async function review(approved:boolean){const token=getToken();if(!token || busy)return;setBusy(true);setError(null);try{const result=await marketplace.reviewPackaging(token,product.id,{target_unit:target,factor:Number(factor),approved,expected_specification_hash:preview?.specification_hash,expected_review_hash:preview?.review_hash});if(approved){await onSaved();setPreview(null);}else setPreview(result);}catch(err){setError(err instanceof Error?russianMessage(err.message):"Не удалось проверить содержимое упаковки.");}finally{setBusy(false);}}
  return <details><summary>Содержимое упаковки и пересчёт</summary>
    <p className="hint">Коэффициент относится к этому товару и его спецификации. Цена, минимальный заказ, склад и сделка сохраняют единицу упаковки; эквивалент содержимого показывается отдельно. При изменении спецификации подтверждение снимается.</p>
    {product.quantity_conversion && <p>Подтверждено: 1 {russianUnit(product.quantity_conversion.from_unit)} = {product.quantity_conversion.factor} {russianUnit(product.quantity_conversion.to_unit)}.</p>}
    <label>Единица содержимого<input value={target} disabled={busy} onChange={event=>{setTarget(event.target.value);setPreview(null);}} /></label>
    <label>Количество в одной упаковке<input type="number" min={1} step={1} value={factor} disabled={busy} onChange={event=>{setFactor(event.target.value);setPreview(null);}} /></label>
    <p className="hint">Дробное содержимое укажите точно в меньшей физической единице, например 2500 г или 1500 мм. Округление запрещено.</p>
    {error && <p role="alert" className="alert alert-error">{error}</p>}
    <button type="button" disabled={busy} onClick={()=>void review(false)}>Проверить пересчёт</button>
    {preview && <div><p>Будет подтверждено: 1 {russianUnit(preview.from_unit)} = {preview.factor} {russianUnit(preview.to_unit)}.</p><button type="button" disabled={busy} onClick={()=>void review(true)}>Содержимое проверено — подтвердить</button></div>}
  </details>;
}

"use client";
import MoneyInput from "./MoneyInput";
import type { CommercialTerms } from '../lib/marketplace';
export const emptyCommercialTerms: CommercialTerms = {delivery_method:'unknown',tax_basis:'unknown',vat_rate_pct:null,expenses:[]};
export default function CommercialTermsFields({value,onChange,disabled=false}:{value:CommercialTerms;onChange:(value:CommercialTerms)=>void;disabled?:boolean}) {
  return <fieldset disabled={disabled}><legend>Доставка и налоговые условия</legend>
    <div className="form-grid">
      <div className="field"><label>Условия доставки<select value={value.delivery_method} onChange={event=>onChange({...value,delivery_method:event.target.value as CommercialTerms['delivery_method']})}>
        <option value="unknown">Нужно уточнить</option><option value="included">Включена в цену</option><option value="separate">Оплачивается отдельно</option><option value="self_pickup">Самовывоз</option>
      </select></label></div>
      <div className="field"><label>Налоговая база<select value={value.tax_basis} onChange={event=>onChange({...value,tax_basis:event.target.value as CommercialTerms['tax_basis'],vat_rate_pct:null})}>
        <option value="unknown">Нужно уточнить</option><option value="no_vat">Без НДС</option><option value="includes_vat">Цена включает НДС</option>
      </select></label></div>
      {value.tax_basis==='includes_vat'&&<div className="field"><label>Включённый НДС, %<input type="number" min="0" max="100" step="0.01" required value={value.vat_rate_pct??''} onChange={event=>onChange({...value,vat_rate_pct:event.target.value})}/></label></div>}
      <div className="field"><label>Условия и место получения<input value={value.delivery_conditions??''} onChange={event=>onChange({...value,delivery_conditions:event.target.value||null})}/></label></div>
      <div className="field"><label>Исключения и ограничения<input value={value.exceptions??''} onChange={event=>onChange({...value,exceptions:event.target.value})}/></label></div>
    </div>
    <p className="hint">Сборы платформы отсутствуют. Предъявленные покупателю дополнительные расходы производителя укажите отдельно. Внутренняя себестоимость заполняется в разделе затрат сделки. Неуточнённые обязательные условия не позволяют окончательно согласовать заказ.</p>
    {(value.expenses??[]).map((expense,index)=><div className="form-grid" key={index}>
      <label>Статья<select value={expense.code} onChange={event=>onChange({...value,expenses:value.expenses!.map((row,i)=>i===index?{...row,code:event.target.value as typeof expense.code}:row)})}><option value="individual_operations">Индивидуальные операции</option><option value="reserve_holding">Удержание резерва</option><option value="switching">При переключении поставщика</option><option value="other">Другой расход</option></select></label>
      <label>Название<input required value={expense.title} onChange={event=>onChange({...value,expenses:value.expenses!.map((row,i)=>i===index?{...row,title:event.target.value}:row)})}/></label>
      <label>Сумма, ₽<MoneyInput min="0" value={expense.amount_rub??''} onChange={event=>onChange({...value,expenses:value.expenses!.map((row,i)=>i===index?{...row,amount_rub:event.target.value||null}:row)})}/></label>
      <label>Источник тарифа<input required value={expense.source} onChange={event=>onChange({...value,expenses:value.expenses!.map((row,i)=>i===index?{...row,source:event.target.value}:row)})}/></label>
      <label>Версия тарифа<input required value={expense.version} onChange={event=>onChange({...value,expenses:value.expenses!.map((row,i)=>i===index?{...row,version:event.target.value}:row)})}/></label>
      <button type="button" className="btn btn-secondary" onClick={()=>onChange({...value,expenses:value.expenses!.filter((_,i)=>i!==index)})}>Удалить статью</button>
    </div>)}
    <button type="button" className="btn btn-secondary" onClick={()=>onChange({...value,expenses:[...(value.expenses??[]),{code:'other',title:'',amount_rub:null,required:true,source:'',version:''}]})}>Добавить расход производителя</button>
  </fieldset>;
}

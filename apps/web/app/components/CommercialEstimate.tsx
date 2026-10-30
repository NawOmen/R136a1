import { formatRub, type CommercialEstimate as Estimate } from '../lib/marketplace';
export default function CommercialEstimate({value}:{value:Estimate|null|undefined}) {
  if(!value) return <p className="hint">Историческая коммерческая смета отсутствует. Она не восстанавливается из текущего каталога.</p>;
  return <div className="card commercial-estimate"><h3>Полная смета</h3>
    {value.lines.map((line,index)=><p key={`${line.code}-${index}`}>{line.title}: {formatRub(line.amount_rub)}{line.conditional?' · условная статья, сейчас не начислена':''}</p>)}
    <p>Налоговая база: {value.terms.tax_basis==='no_vat'?'Без НДС':value.terms.tax_basis==='includes_vat'?`Включая НДС ${value.terms.vat_rate_pct}%`:'Нужно уточнить'}</p>
    <p>Условия получения: {value.terms.delivery_conditions||'Не указаны'}</p>
    {value.terms.exceptions&&<p>Исключения: {value.terms.exceptions}</p>}
    <strong>{value.complete?'Итого':'Известная часть'}: {formatRub(value.complete?value.total_rub:value.known_total_rub)}</strong>
    {!value.complete&&<div className="alert alert-error">{value.missing.join('; ')}. Окончательное согласование недоступно.</div>}
  </div>;
}

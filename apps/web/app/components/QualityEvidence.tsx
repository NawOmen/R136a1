"use client";
import { russianMessage } from "../lib/russianMessages";
import { displayValue } from "../lib/presentation";
import {useEffect,useState} from "react";
import {getToken} from "../lib/api";
import {marketplace} from "../lib/marketplace";

type Evidence = Awaited<ReturnType<typeof marketplace.getQualityEvidence>>;
export default function QualityEvidence({companyId,onSaved}:{companyId:string;onSaved:()=>void}) {
  const [data,setData]=useState<Evidence|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [pending,setPending]=useState(false);
  const [refresh,setRefresh]=useState(0);
  const [runId,setRunId]=useState(""); const [bankId,setBankId]=useState("");
  const [source,setSource]=useState(""); const [scope,setScope]=useState("");
  const [category,setCategory]=useState(""); const [reference,setReference]=useState("{}");
  const [approved,setApproved]=useState(false); const [applicable,setApplicable]=useState(false);
  const [message,setMessage]=useState("");
  useEffect(()=>{
    let active=true;const token=getToken(); if(!token)return;
    setPending(true);setError(null);
    marketplace.getQualityEvidence(token,companyId).then(v=>{if(active)setData(v);})
      .catch((e:Error)=>{if(active)setError(e.message);}).finally(()=>{if(active)setPending(false);});
    return()=>{active=false;};
  },[companyId,refresh]);
  const selected=data?.runs.find(r=>r.run_id===runId);
  async function save(e:React.FormEvent) {
    e.preventDefault();const token=getToken();if(!token || !approved)return;
    setPending(true);setError(null);setMessage("");
    try {
      let fields:unknown=JSON.parse(reference);
      if(!fields || Array.isArray(fields) || typeof fields!=="object")throw new Error("Эталонные поля должны быть объектом.");
      fields = Object.fromEntries(Object.entries(fields as Record<string, unknown>).map(([key,value]) => [({"Количество":"quantity_units","Бюджет":"budget_rub","Срок":"lead_time_days","Город доставки":"delivery_city","Объём, мл":"volume_ml"} as Record<string,string>)[key] ?? key,value]));
      const result=await marketplace.saveQualityEvidence(token,companyId,{run_id:runId,source,task_scope:scope,
        bank_task_id:bankId||undefined,bank_applicability_confirmed:applicable,critical_fields:fields as Record<string,unknown>,
        expected_category:category||undefined,human_approved:true});
      setMessage(`Проверка сохранена. Правильных признаков: ${result.assessment.correct} из ${result.assessment.total}; заполнено: ${result.assessment.present}.`);
      setApproved(false);onSaved();
    }catch(e){setError(e instanceof SyntaxError?"Проверьте запись полей: названия в кавычках, значения после двоеточия.":e instanceof Error?russianMessage(e.message):"Не удалось сохранить оценку.");}
    finally{setPending(false);}
  }
  return <section className="card"><h2>Экспертная проверка результата</h2><p className="hint">Администратор компании задаёт эталон по исходному заданию. Правильность рассчитывается по первому результату агента, до уточнений человеком. Проверка сохраняет источник, автора, версии и эталон.</p>
    {pending && <p role="status">Загрузка или сохранение проверки…</p>}
    {error && <div role="alert" className="alert alert-error">{error}<button type="button" className="btn btn-secondary" onClick={()=>setRefresh(n=>n+1)}>Повторить загрузку</button></div>}
    {message && <p role="status">{message}</p>}
    {data && (!data.runs.length?<p>Нет прогонов с сохранённым исходным результатом.</p>:<form onSubmit={e=>void save(e)} className="form-grid">
      <div className="field"><label htmlFor="quality-run">Прогон</label><select id="quality-run" required value={runId} onChange={e=>{setRunId(e.target.value);setApproved(false);setApplicable(false);}}><option value="">Выберите</option>{data.runs.map(r=><option key={r.run_id} value={r.run_id}>{r.role==="buyer_agent"?"Покупатель":"Продавец"} · {r.run_id.slice(0,8)}</option>)}</select></div>
      {selected && <details><summary>Исходный результат для сверки</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{displayValue(selected.initial_result)}</pre></details>}
      <div className="field"><label htmlFor="quality-bank">Эталон</label><select id="quality-bank" value={bankId} onChange={e=>{setBankId(e.target.value);setApplicable(false);setApproved(false);}}><option value="">Экспертные поля</option>{selected?.role==="buyer_agent" && data.bank_tasks.map(t=><option key={t.id} value={t.id}>{t.id} · {t.expected_category}</option>)}</select></div>
      {bankId?<><p>{data.bank_tasks.find(t=>t.id===bankId)?.input_text}</p><label><input type="checkbox" checked={applicable} onChange={e=>setApplicable(e.target.checked)} required />Исходное задание соответствует этой задаче банка, включая её дополнительные источники и условия</label></>:<><div className="field"><label htmlFor="quality-category">Эталонная категория</label><input id="quality-category" value={category} onChange={e=>{setCategory(e.target.value);setApproved(false);}} /></div><div className="field"><label htmlFor="quality-reference">Эталонные критичные поля</label><textarea id="quality-reference" value={reference} onChange={e=>{setReference(e.target.value);setApproved(false);}} placeholder={'{"Количество":5000}'} /></div></>}
      <div className="field"><label htmlFor="quality-scope">Сопоставимый класс задачи</label><input id="quality-scope" value={scope} onChange={e=>{setScope(e.target.value);setApproved(false);}} required minLength={3} maxLength={120}/></div>
      <div className="field"><label htmlFor="quality-source">Источник экспертной сверки</label><input id="quality-source" value={source} onChange={e=>{setSource(e.target.value);setApproved(false);}} required minLength={3} maxLength={1000}/></div>
      <label><input type="checkbox" required checked={approved} onChange={e=>setApproved(e.target.checked)}/>Я сверил исходное задание, применимость и эталон; подтверждаю сохранение проверки</label>
      <button className="btn btn-primary" disabled={pending || !approved || !runId || (!!bankId&&!applicable)}>Сохранить экспертную проверку</button>
    </form>)}
  </section>;
}

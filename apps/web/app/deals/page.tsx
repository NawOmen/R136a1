"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, Company, getToken } from "../lib/api";
import { Deal, DealMessage, formatRub, formatUnits, marketplace } from "../lib/marketplace";

export default function DealsPage() {
  const [companies, setCompanies] = useState<Company[]>([]); const [deals, setDeals] = useState<Deal[]>([]);
  const [selected, setSelected] = useState<Deal | null>(null); const [messages, setMessages] = useState<DealMessage[]>([]); const [draft, setDraft] = useState(""); const [error, setError] = useState<string | null>(null);
  const companyId = selected ? companies.find((c) => c.id === selected.buyer_company_id || c.id === selected.seller_company_id)?.id : undefined;
  useEffect(() => { const token=getToken(); if (!token) return; Promise.all([api.me(token),marketplace.getMyDeals(token)]).then(([me,list])=>{setCompanies(me.companies);setDeals(list);setSelected(list[0]??null);}).catch((e:Error)=>setError(e.message)); },[]);
  useEffect(() => { const token=getToken(); if (!token || !selected || !companyId) return; marketplace.getDealMessages(token,selected.id,companyId).then(setMessages).catch((e:Error)=>setError(e.message)); },[selected,companyId]);
  async function send(event:FormEvent){event.preventDefault();const token=getToken();if(!token||!selected||!companyId||!draft.trim())return;await marketplace.sendDealMessage(token,selected.id,companyId,draft);setDraft("");setMessages(await marketplace.getDealMessages(token,selected.id,companyId));}
  return <div><h1>Сделки и сообщения</h1><p className="subtitle">Внутренняя связь покупателя и производителя</p>{error&&<div className="alert alert-error">{error}</div>}
    <div className="deal-layout"><aside className="card"><h2>Мои сделки</h2>{deals.length===0?<p className="hint">Сделок пока нет.</p>:deals.map((deal)=><button type="button" className="deal-button" key={deal.id} onClick={()=>setSelected(deal)}>{formatUnits(deal.units)} · {formatRub(deal.total_price_rub)}</button>)}</aside>
    <section className="card"><h2>Переписка</h2>{!selected?<p className="hint">Выберите сделку.</p>:<><div className="message-list">{messages.length===0?<p className="hint">Начните обсуждение условий.</p>:messages.map((m)=><p key={m.id}><b>{m.author_company_id===companyId?"Ваша компания":"Участник сделки"}</b><br/>{m.message}</p>)}</div><form onSubmit={send}><div className="field"><label htmlFor="deal-message">Сообщение</label><textarea id="deal-message" maxLength={2000} value={draft} onChange={(e)=>setDraft(e.target.value)} /></div><button className="btn btn-primary">Отправить</button></form></>}</section></div>
  </div>;
}

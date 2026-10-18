"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { agents } from "../lib/agents";
import { getToken } from "../lib/api";

const FAQ = [
  ["Можно одновременно покупать и продавать?", "Да. Участник компании включает оба права и переключает рабочий режим без второй регистрации."],
  ["Что делает ИИ?", "Помогает собрать требования, найти кандидатов и объяснить расчёт. Деньги и ресурсы рассчитывает программный код. Критичные действия подтверждает человек."],
  ["Кто организует перевозку?", "Покупатель выбирает перевозчика или самовывоз; продавец сообщает параметры груза и окно отгрузки. ПоРукам ведёт чек-лист, но не перевозит груз."],
  ["Когда можно оставить отзыв?", "Участнику сделки после подтверждённой приёмки, если исполнение не полностью возвращено и нет незавершённого возврата."],
  ["Как работает объединение заказов?", "Система объединяет совместимый спрос только при подтверждённой экономической выгоде и отдельном согласии каждого участника."],
];

export default function KnowledgePage() {
  const [question,setQuestion]=useState("");
  const [answer,setAnswer]=useState("");
  const [links,setLinks]=useState<string[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);

  async function ask(event:FormEvent){
    event.preventDefault();
    const token=getToken();
    if(busy) return;
    if(!token){setError("Войдите, чтобы задать вопрос ИИ-помощнику.");return;}
    setBusy(true);setError(null);setAnswer("");setLinks([]);
    try{
      const result=await agents.askPlatform(token,question);
      setAnswer(result.answer);
      setLinks((result.links ?? []).filter((link) => ["/needs/new", "/dashboard", "/deals", "/support"].includes(link)));
    }catch(e){setError(e instanceof Error?russianMessage(e.message):"Помощник недоступен. Проверьте соединение и повторите.");}
    finally{setBusy(false);}
  }

  return <div><h1>Помощь и база знаний</h1><p className="subtitle">Ответы о работе ПоРукам и локальный ИИ-помощник</p><div className="knowledge-layout"><section aria-label="Частые вопросы">{FAQ.map(([title,body])=><details className="card faq" key={title}><summary>{title}</summary><p>{body}</p></details>)}</section><aside className="card assistant-card"><h2>Спросить помощника</h2><p className="hint">Помощник отвечает только по проверенной справке платформы, показывает источник и не принимает финансовых решений. Не указывайте пароли и персональные данные.</p><form onSubmit={ask}><div className="field"><label htmlFor="assistant-question">Ваш вопрос</label><textarea id="assistant-question" disabled={busy} maxLength={1000} minLength={3} required value={question} onChange={(e)=>setQuestion(e.target.value)}/></div><button className="btn btn-primary" disabled={busy}>{busy?"Думаю…":"Спросить"}</button></form>{error&&<div className="alert alert-error" role="alert">{error} <button type="button" className="btn btn-secondary btn-sm" onClick={()=>setError(null)}>Понятно</button></div>}{answer&&<div className="assistant-answer" aria-live="polite"><p>{answer}</p><p className="hint">Источник: справка платформы ПоРукам. Финансовые решения помощник не принимает.</p>{links.length>0&&<ul>{links.map((link)=><li key={link}><Link href={link}>{({"/needs/new":"Создать потребность","/dashboard":"Компании и права","/deals":"Согласование и исполнение","/support":"Поддержка"} as Record<string,string>)[link]}</Link></li>)}</ul>}</div>}<Link href="/support">Не нашли ответ? Написать в поддержку</Link></aside></div></div>;
}

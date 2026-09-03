"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { agents } from "../lib/agents";
import { getToken } from "../lib/api";

const FAQ = [
  ["Можно одновременно покупать и продавать?", "Да. Участник компании включает оба права и переключает рабочий режим без второй регистрации."],
  ["Что делает ИИ?", "Помогает собрать требования, найти кандидатов и объяснить расчёт. Цена, мощность, резерв и сделка меняются только после подтверждения человека."],
  ["Кто организует перевозку?", "Покупатель выбирает перевозчика или самовывоз; продавец сообщает параметры груза и окно отгрузки. ПоРукам ведёт чек-лист, но не перевозит груз."],
  ["Когда можно оставить отзыв?", "Только участнику сделки после того, как покупатель подтвердил получение товара."],
  ["Как работает объединение заказов?", "Система объединяет совместимый спрос только при подтверждённой экономической выгоде и отдельном согласии каждого участника."],
];

export default function KnowledgePage() {
  const [question,setQuestion]=useState(""); const [answer,setAnswer]=useState(""); const [busy,setBusy]=useState(false); const [error,setError]=useState<string|null>(null);
  async function ask(event:FormEvent){event.preventDefault();const token=getToken();if(!token){setError("Войдите, чтобы задать вопрос ИИ-помощнику.");return;}setBusy(true);setError(null);try{setAnswer((await agents.askPlatform(token,question)).answer);}catch(e){setError(e instanceof Error?e.message:"Помощник недоступен.");}finally{setBusy(false);}}
  return <div><h1>Помощь и база знаний</h1><p className="subtitle">Ответы о работе ПоРукам и локальный ИИ-помощник</p><div className="knowledge-layout"><section>{FAQ.map(([title,body])=><details className="card faq" key={title}><summary>{title}</summary><p>{body}</p></details>)}</section><aside className="card assistant-card"><h2>Спросить помощника</h2><p className="hint">Помощник отвечает по правилам платформы и не совершает действий.</p><form onSubmit={ask}><div className="field"><label htmlFor="assistant-question">Ваш вопрос</label><textarea id="assistant-question" minLength={3} required value={question} onChange={(e)=>setQuestion(e.target.value)}/></div><button className="btn btn-primary" disabled={busy}>{busy?"Думаю…":"Спросить"}</button></form>{error&&<div className="alert alert-error">{error}</div>}{answer&&<div className="assistant-answer">{answer}</div>}<Link href="/support">Не нашли ответ? Написать в поддержку</Link></aside></div></div>;
}

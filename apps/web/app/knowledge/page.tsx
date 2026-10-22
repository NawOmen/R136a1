"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { agents } from "../lib/agents";
import { getToken } from "../lib/api";
import { Icon } from "../components/Icon";
import { LiquidSurface } from "../components/LiquidSurface";
import { HeroObject } from "../components/HeroObject";

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

  return <div className="guidance-page help-page">
    <LiquidSurface as="header" variant="help" className="guidance-hero help-hero">
      <div className="guidance-hero__copy"><h1>Помощь с закупкой</h1><p className="guidance-lead">Ответы о работе ПоРукам и локальный ИИ-помощник</p>
      <nav className="help-shortcuts" aria-label="Быстрые действия">
        <Link className="toggle-motion" href="/needs/new"><Icon name="layers" size={22} /><span>Создать потребность</span><Icon name="arrow" size={19} /></Link>
        <Link className="toggle-motion" href="/support"><Icon name="link" size={22} /><span>Написать в поддержку</span><Icon name="arrow" size={19} /></Link>
      </nav></div>
      <HeroObject kind="help" />
    </LiquidSurface>
    <div className="help-layout">
      <section className="help-questions" aria-labelledby="faq-heading"><h2 id="faq-heading">Частые вопросы</h2><div className="guidance-disclosures">{FAQ.map(([title,body]) => <details className="guidance-disclosure" key={title}><summary><span>{title}</span><Icon name="arrow" size={19} /></summary><div className="guidance-disclosure__body"><p>{body}</p></div></details>)}</div></section>
      <aside className="help-assistant">
        <h2><Icon name="spark" size={25} />Спросить помощника</h2>
        <p className="hint">Отвечает по проверенной справке со ссылкой на источник. Не принимает финансовых решений. Не указывайте пароли и персональные данные.</p>
        <form onSubmit={ask}><div className="field"><label htmlFor="assistant-question">Ваш вопрос</label><textarea id="assistant-question" disabled={busy} maxLength={1000} minLength={3} required value={question} onChange={(e)=>setQuestion(e.target.value)} placeholder="Например, как согласовать условия сделки?" /></div><button className="btn btn-primary" disabled={busy}>{busy?"Думаю…":"Спросить"}<Icon name="arrow" size={18} /></button></form>
        {error && <div className="alert alert-error" role="alert">{error} <button type="button" className="btn btn-secondary btn-sm" onClick={()=>setError(null)}>Понятно</button></div>}
        {answer && <div className="assistant-answer" aria-live="polite"><p>{answer}</p><p className="hint">Источник: справка ПоРукам.</p>{links.length>0 && <ul>{links.map(link => <li key={link}><Link href={link}>{({"/needs/new":"Создать потребность","/dashboard":"Компании и права","/deals":"Согласование и исполнение","/support":"Поддержка"} as Record<string,string>)[link]}</Link></li>)}</ul>}</div>}
        <Link className="help-support-link" href="/support">Не нашли ответ? Написать в поддержку<Icon name="arrow" size={17} /></Link>
      </aside>
    </div>
  </div>;
}

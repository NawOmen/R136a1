"use client";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import { marketplace, SupportTicket } from "../lib/marketplace";
import { useMe } from "../lib/useMe";
import { Icon } from "../components/Icon";

const SUPPORT_TOPICS = [
  "Личный вопрос", "Аккаунт и доступ", "Компания и сотрудники", "Проверка компании",
  "Товары и каталог", "Создание потребности", "Закупка с ИИ", "Предложения производителей",
  "Сделки и согласование условий", "Оплата и расчёты", "Доставка и получение",
  "Возврат и расхождения", "Документы и правила", "Техническая ошибка", "Предложение по улучшению",
];

export default function SupportPage() {
  const { companies } = useMe();
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [topic, setTopic] = useState(SUPPORT_TOPICS[0]);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const [sendError, setSendError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const end = useRef<HTMLDivElement>(null);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      const token = getToken(); if (!token) { setLoading(false); return; }
      const version = ++generation.current;
      void marketplace.getMySupportTickets(token).then(value => { if (active && version === generation.current) { setTickets(value); setLoadError(""); } })
        .catch(() => { if (active && version === generation.current) setLoadError("Не удалось загрузить переписку. Ваш текст сохранён, повторите загрузку."); })
        .finally(() => { if (active) setLoading(false); });
    };
    refresh(); const timer = setInterval(refresh, 15000);
    return () => { active = false; clearInterval(timer); };
  }, [retry]);
  const messages = tickets.flatMap(t => [
    { id: t.id, text: t.message, date: t.created_at, support: false, topic: t.subject.startsWith("Поддержка: ") ? t.subject.slice(11) : undefined, company: companies.find(c => c.id === t.company_id)?.display_name },
    ...(t.admin_response ? [{ id: `${t.id}:answer`, text: t.admin_response, date: t.updated_at, support: true, topic: undefined, company: undefined }] : []),
  ]).sort((a,b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages.length]);
  async function submit(event: FormEvent) {
    event.preventDefault(); const token = getToken(); if (!token || busy || !message.trim()) return;
    setBusy(true); setSendError(""); ++generation.current;
    try {
      const text = message.trim();
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([companyId, topic, text]))))).map(v => v.toString(16).padStart(2,"0")).join("");
      const key = `porukam:support:${hash}`;
      const requestKey = sessionStorage.getItem(key) ?? crypto.randomUUID(); sessionStorage.setItem(key, requestKey);
      const ticket = await marketplace.createSupportTicket(token, { request_key: requestKey, ...(companyId ? { company_id: companyId } : {}), subject: `Поддержка: ${topic}`, message: text });
      ++generation.current; sessionStorage.removeItem(key);
      setTickets(current => [ticket, ...current.filter(t => t.id !== ticket.id)]); setMessage("");
    } catch { setSendError("Сообщение не отправлено. Текст сохранён — попробуйте ещё раз."); }
    finally { setBusy(false); }
  }
  return <div className="support-chat-page"><div className="company-row"><div><h1>Чат с поддержкой</h1><p className="subtitle">Задайте вопрос — ответ сотрудника появится здесь.</p></div><Link className="btn btn-secondary" href="/dashboard">В личный кабинет</Link></div>
    <section className="support-chat card" aria-label="Переписка с поддержкой">
      <div className="support-chat__header"><Icon name="mail" /><div><strong>Команда ПоРукам</strong><p className="hint">Ответы сохраняются в чате и уведомлениях</p></div></div>
      {loadError && <p className="alert alert-error" role="alert">{loadError} <button className="btn btn-secondary btn-sm" onClick={() => setRetry(v=>v+1)}>Повторить загрузку</button></p>}
      {sendError && <p className="alert alert-error" role="alert">{sendError}</p>}
      <div className="support-chat__messages" role="log" aria-label="Сообщения" aria-live="polite" aria-busy={loading}>
        {loading ? <p role="status">Загружаем переписку…</p> : !messages.length && !loadError && !sendError ? <div className="support-chat__empty"><Icon name="mail" size={32} /><h2>Чем помочь?</h2><p>Опишите вопрос, при необходимости укажите номер сделки.</p></div> : messages.map(m => <article key={m.id} className={`chat-bubble ${m.support ? "chat-bubble--support" : "chat-bubble--user"}`}><small>{m.support ? "Поддержка" : "Вы"}{m.company ? ` · ${m.company}` : ""}{m.topic ? ` · ${m.topic}` : ""}</small><p>{m.text}</p><time dateTime={m.date}>{new Date(m.date).toLocaleString("ru-RU", { day:"numeric",month:"short",hour:"2-digit",minute:"2-digit" })}</time></article>)}<div ref={end} />
      </div>
      <form className="support-chat__composer" onSubmit={submit}><div className="support-chat__context"><div><label htmlFor="support-topic">Тема вопроса</label><select id="support-topic" value={topic} disabled={busy} onChange={e=>setTopic(e.target.value)}>{SUPPORT_TOPICS.map(item=><option key={item}>{item}</option>)}</select></div><div><label htmlFor="support-company">Компания</label><select id="support-company" value={companyId} disabled={busy} onChange={e=>setCompanyId(e.target.value)}><option value="">Без привязки к компании</option>{companies.map(c=><option key={c.id} value={c.id}>{c.display_name}</option>)}</select></div></div><label className="visually-hidden" htmlFor="support-message">Сообщение поддержке</label><textarea id="support-message" placeholder="Напишите сообщение…" minLength={1} maxLength={5000} required disabled={busy} value={message} onChange={e=>setMessage(e.target.value)} /><div className="company-row"><span className="hint">Не отправляйте пароли и секреты.</span><button className="btn btn-primary" disabled={busy}>{busy ? "Отправляем…" : "Отправить"}<Icon name="arrow" /></button></div></form>
    </section></div>;
}

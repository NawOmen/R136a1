"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { ApiError, marketplace, SupportTicket } from "../lib/marketplace";
import { useMe } from "../lib/useMe";

const STATUS: Record<SupportTicket["status"], string> = {
  new: "Новое", in_progress: "В работе", resolved: "Решено", closed: "Закрыто",
};

export default function SupportPage() {
  const { companies } = useMe();
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const token = getToken();
    if (token) setTickets(await marketplace.getMySupportTickets(token));
  }
  useEffect(() => { void refresh().catch(() => setError("Не удалось загрузить обращения.")); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const token = getToken();
    if (!token) return;
    setBusy(true); setError(null);
    try {
      await marketplace.createSupportTicket(token, {
        ...(companyId ? { company_id: companyId } : {}), subject, message,
      });
      setSubject(""); setMessage(""); await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить обращение.");
    } finally { setBusy(false); }
  }

  return <div>
    <div className="company-row"><h1 className="page-title">Поддержка</h1><Link href="/dashboard" className="btn btn-secondary btn-sm">На главную</Link></div>
    <p className="subtitle">Не указывайте пароли, секреты и лишние персональные данные.</p>
    {error && <div className="alert alert-error">{error}</div>}
    <div className="support-layout"><aside className="support-history card"><h2>Мои обращения</h2>
      {tickets.length === 0 ? <p className="hint">Обращений пока нет.</p> : <ul>{tickets.map((ticket) => <li key={ticket.id}><div className="company-row"><strong>{ticket.subject}</strong><span className="badge">{STATUS[ticket.status]}</span></div><p>{ticket.message}</p>{ticket.admin_response && <div className="alert alert-success">Ответ поддержки: {ticket.admin_response}</div>}</li>)}</ul>}
    </aside><form className="card support-form" onSubmit={(event) => void submit(event)}><h2>Новое обращение</h2>
      <div className="field"><label htmlFor="support-company">Компания (необязательно)</label><select id="support-company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}><option value="">Без привязки</option>{companies.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></div>
      <div className="field"><label htmlFor="support-subject">Тема</label><input id="support-subject" type="text" minLength={3} maxLength={200} required value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
      <div className="field"><label htmlFor="support-message">Сообщение</label><textarea id="support-message" minLength={10} maxLength={5000} required value={message} onChange={(e) => setMessage(e.target.value)} /></div>
      <button className="btn btn-primary" disabled={busy}>{busy ? "Отправляем…" : "Отправить"}</button>
    </form></div>
  </div>;
}

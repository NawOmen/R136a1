"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { getToken } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/dates";
import { formatUnits } from "../lib/marketplace";
import { russianMessage } from "../lib/russianMessages";
import { supplierWorkflow as api, type SupplierMessage, type SupplierRequest } from "../lib/supplierWorkflow";

export default function SupplierConversation({ row, companyId, canManage, onChanged }: { row: SupplierRequest; companyId: string; canManage: boolean; onChanged: () => Promise<void> }) {
  const buyer = companyId === row.buyer_company_id;
  const [messages, setMessages] = useState<SupplierMessage[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [message, setMessage] = useState(""), [aiDraft, setAiDraft] = useState(false), [aiWarnings, setAiWarnings] = useState<string[]>([]);
  const sending = useRef<{ text: string; key: string } | null>(null), mounted = useRef(true), historyGeneration = useRef(0);
  const id = row.id;
  async function reload() {
    const token = getToken(); if (!token) return;
    const current = ++historyGeneration.current;
    const history = await api.messages(token, id, companyId);
    if (!mounted.current || current !== historyGeneration.current) return;
    setMessages(history);
  }
  useEffect(() => {
    mounted.current = true;
    void reload().catch(e => { if (mounted.current) setError(russianMessage(e.message)); }).finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; historyGeneration.current++; };
  }, [id, companyId, row.revision]);
  async function perform(action: (token: string) => Promise<void>) {
    const token = getToken(); if (!token || busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await action(token); }
    catch (e) { if (mounted.current) setError(e instanceof Error ? russianMessage(e.message) : "Не удалось выполнить действие. Повторите попытку."); }
    finally { if (mounted.current) setBusy(false); }
  }
  function send(event: FormEvent) {
    event.preventDefault();
    const value = message.trim(); if (!value) return;
    if (sending.current?.text !== value) sending.current = { text: value, key: crypto.randomUUID() };
    const key = sending.current.key;
    void perform(async token => {
      await api.send(token, id, companyId, value, row.revision, key);
      if (!mounted.current) return;
      sending.current = null; setMessage(""); setAiDraft(false); setNotice("Сообщение отправлено.");
      await Promise.all([reload(), onChanged()]);
    });
  }
  function draft() {
    void perform(async token => {
      const result = await api.draft(token, row, companyId, buyer && row.status === "draft" ? "rfq" : "reply", message.slice(0, 1500));
      if (mounted.current) { setMessage(result.text); setAiDraft(true); setAiWarnings(result.warnings ?? []); setNotice("Черновик готов. Проверьте текст перед отправкой."); }
    });
  }
  return <section className="supplier-workspace" aria-label="Работа с поставщиком" aria-busy={busy}>
    <header className="supplier-workspace__heading"><div><h3>{buyer ? row.seller_name : row.buyer_name}</h3><p className="hint">{row.specification.category} · {formatUnits(row.specification.quantity, row.specification.unit)} · до {formatDate(row.specification.deadline_date)}</p></div><button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void perform(async () => { await Promise.all([reload(), onChanged()]); setNotice("Переписка обновлена."); })}>Обновить</button></header>
    {error && <p className="alert alert-error" role="alert">{error}</p>}
    {notice && <p className="hint" role="status">{notice}</p>}
    <div className="supplier-dialogue">
      <h4>Чат</h4>
        {loading ? <p role="status">Загружаем переписку…</p> : !messages.length ? <p className="hint">{row.status === "draft" ? "Запрос увидит только выбранный поставщик после отправки." : "Сообщений на платформе пока нет."}</p> : <ol className="supplier-messages">{messages.map(m => <li key={m.id} className={m.author_company_id === companyId ? "supplier-message supplier-message--own" : "supplier-message"}><div><b>{m.author_company_id === row.buyer_company_id ? row.buyer_name : row.seller_name}</b><time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time></div><p>{m.message}</p></li>)}</ol>}
        <form onSubmit={send} className="supplier-composer"><label htmlFor={`supplier-message-${id}`}>{row.status === "draft" ? "Запрос коммерческого предложения" : "Ваше сообщение"}</label><textarea id={`supplier-message-${id}`} value={message} required maxLength={6000} rows={5} disabled={busy} onChange={e => { setMessage(e.target.value); setAiDraft(false); }} placeholder="Напишите сообщение или поручите черновик ИИ" />
          {aiDraft && <p className="hint">Черновик ИИ. Проверьте факты, цену и срок.</p>}
          {aiDraft && aiWarnings.map(warning => <p className="alert alert-warning" key={warning}>{warning}</p>)}
          <div className="actions"><button type="button" className="btn btn-secondary" disabled={busy || loading} onClick={draft}>{busy ? "Обрабатываем…" : row.status === "draft" && buyer ? "Подготовить запрос с ИИ" : "Помочь с ответом"}</button><button type="submit" className="btn btn-primary" disabled={busy || loading || !message.trim() || (row.status === "draft" && !canManage)}>{buyer ? "Отправить поставщику" : "Отправить покупателю"}</button></div>
        </form>
    </div>
  </section>;
}

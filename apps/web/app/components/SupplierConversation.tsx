"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { getToken } from "../lib/api";
import { FilePicker } from "./FilePicker";
import { DateInput } from "./DateInput";
import { formatDate, formatDateTime } from "../lib/dates";
import { formatRub, formatUnits } from "../lib/marketplace";
import { russianMessage } from "../lib/russianMessages";
import { supplierWorkflow as api, updateValues, saveDownload, type PriceBasis, type QuoteProposal, type SupplierFile, type SupplierMessage, type SupplierRequest } from "../lib/supplierWorkflow";

export default function SupplierConversation({ row, companyId, canManage, onChanged }: { row: SupplierRequest; companyId: string; canManage: boolean; onChanged: () => Promise<void> }) {
  const buyer = companyId === row.buyer_company_id;
  const [messages, setMessages] = useState<SupplierMessage[]>([]), [files, setFiles] = useState<SupplierFile[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [message, setMessage] = useState(""), [aiDraft, setAiDraft] = useState(false), [aiWarnings, setAiWarnings] = useState<string[]>([]);
  const [price, setPrice] = useState(row.quoted_price_rub == null ? "" : String(row.quoted_price_rub)), [basis, setBasis] = useState<PriceBasis>(row.price_basis);
  const [days, setDays] = useState(row.lead_time_days == null ? "" : String(row.lead_time_days)), [delivery, setDelivery] = useState(row.delivery_date ?? ""), [note, setNote] = useState(row.note);
  const [proposal, setProposal] = useState<QuoteProposal | null>(null);
  const sending = useRef<{ text: string; key: string } | null>(null), mounted = useRef(true), dirty = useRef(false), historyGeneration = useRef(0);
  const id = row.id;
  async function reload() {
    const token = getToken(); if (!token) return;
    const current = ++historyGeneration.current;
    const [history, attachments] = await Promise.all([api.messages(token, id, companyId), buyer ? api.files(token, id, companyId) : Promise.resolve([])]);
    if (!mounted.current || current !== historyGeneration.current) return;
    setMessages(history); setFiles(attachments);
  }
  useEffect(() => {
    mounted.current = true;
    void reload().catch(e => { if (mounted.current) setError(russianMessage(e.message)); }).finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; historyGeneration.current++; };
  }, [id, companyId, row.revision]);
  useEffect(() => {
    if (dirty.current) return;
    setPrice(row.quoted_price_rub == null ? "" : String(row.quoted_price_rub)); setBasis(row.price_basis);
    setDays(row.lead_time_days == null ? "" : String(row.lead_time_days)); setDelivery(row.delivery_date ?? ""); setNote(row.note);
  }, [row.revision]);
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
  function upload(file: File) {
    void perform(async token => {
      const saved = await api.upload(token, id, companyId, file);
      await reload();
      if (!mounted.current) return;
      setNotice("Файл сохранён. Разбираем цену и срок…");
      const result = await api.extract(token, row, companyId, saved.id);
      if (!mounted.current) return;
      setProposal(result); setPrice(result.price_rub ?? ""); setBasis(result.price_basis); setDays(result.lead_time_days == null ? "" : String(result.lead_time_days)); setDelivery(result.delivery_date ?? "");
      dirty.current = true; setNotice("Проверьте данные из файла и сохраните ответ.");
    });
  }
  function saveQuote(event: FormEvent) {
    event.preventDefault();
    void perform(async token => {
      await api.update(token, id, { ...updateValues(row, row.status === "sent" ? "replied" : row.status), quoted_price_rub: price === "" ? null : price.replace(",", "."), price_basis: basis, lead_time_days: days === "" ? null : Number(days), delivery_date: delivery || null, note: note.trim() });
      dirty.current = false; await onChanged(); setNotice("Ответ сохранён. Условия сделки не изменены.");
    });
  }
  return <section className="supplier-workspace" aria-label="Работа с поставщиком" aria-busy={busy}>
    <header className="supplier-workspace__heading"><div><h3>{buyer ? row.seller_name : row.buyer_name}</h3><p className="hint">{row.specification.category} · {formatUnits(row.specification.quantity, row.specification.unit)} · до {formatDate(row.specification.deadline_date)}</p></div><button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void perform(async () => { await Promise.all([reload(), onChanged()]); setNotice("Переписка обновлена."); })}>Обновить</button></header>
    {!buyer && <p className="hint">Доска ответов и заметки покупателя приватны. Согласованные условия — в КП и заказе.</p>}
    {error && <p className="alert alert-error" role="alert">{error}</p>}
    {notice && <p className="hint" role="status">{notice}</p>}
    <div className={`supplier-workspace__columns${buyer && row.status !== "draft" ? "" : " supplier-workspace__columns--single"}`}>
      <div className="supplier-dialogue"><h4>Переписка</h4>
        {loading ? <p role="status">Загружаем переписку…</p> : !messages.length ? <p className="hint">{row.status === "draft" ? "Запрос увидит только выбранный поставщик после отправки." : "Сообщений на платформе пока нет."}</p> : <ol className="supplier-messages">{messages.map(m => <li key={m.id} className={m.author_company_id === companyId ? "supplier-message supplier-message--own" : "supplier-message"}><div><b>{m.author_company_id === row.buyer_company_id ? row.buyer_name : row.seller_name}</b><time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time></div><p>{m.message}</p></li>)}</ol>}
        <form onSubmit={send} className="supplier-composer"><label htmlFor={`supplier-message-${id}`}>{row.status === "draft" ? "Запрос коммерческого предложения" : "Ваше сообщение"}</label><textarea id={`supplier-message-${id}`} value={message} required maxLength={6000} rows={5} disabled={busy} onChange={e => { setMessage(e.target.value); setAiDraft(false); }} placeholder="Напишите сообщение или поручите черновик ИИ" />
          {aiDraft && <p className="hint">Черновик ИИ. Проверьте факты, цену и срок.</p>}
          {aiDraft && aiWarnings.map(warning => <p className="alert alert-warning" key={warning}>{warning}</p>)}
          <div className="actions"><button type="button" className="btn btn-secondary" disabled={busy || loading} onClick={draft}>{busy ? "Обрабатываем…" : row.status === "draft" && buyer ? "Подготовить запрос с ИИ" : "Помочь с ответом"}</button><button type="submit" className="btn btn-primary" disabled={busy || loading || !message.trim() || (row.status === "draft" && !canManage)}>{buyer ? "Отправить поставщику" : "Отправить покупателю"}</button><button type="button" className="btn btn-secondary btn-sm" disabled={busy || !message.trim()} onClick={() => void perform(async () => { if (!navigator.clipboard) throw new Error("Выделите текст и скопируйте его вручную."); await navigator.clipboard.writeText(message); setNotice("Текст скопирован для почты или мессенджера."); })}>Скопировать</button></div>
          {buyer && row.status === "draft" && canManage && <button type="button" className="supplier-external-send" disabled={busy} onClick={() => void perform(async token => { await api.update(token, id, updateValues(row, "sent")); await onChanged(); setNotice("Отправка вне платформы отмечена на доске."); })}>Я отправил запрос вне платформы</button>}
        </form>
      </div>
      {buyer && row.status !== "draft" && <div className="supplier-reply"><h4>Ответ поставщика</h4>
        {canManage && <div className="supplier-upload"><span>{busy ? "Обрабатываем ответ…" : "Приложить ответ: PDF или фото"}</span><FilePicker aria-label="Файл ответа поставщика" status={files.length ? `Прикреплено файлов: ${files.length}` : undefined} accept="application/pdf,image/png,image/jpeg,image/webp,text/plain" disabled={busy} onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (file) upload(file); }} /></div>}
        {!!files.length && <ul className="supplier-files">{files.map(f => <li key={f.id}><button type="button" disabled={busy} onClick={() => void perform(async token => saveDownload(await api.download(token, id, companyId, f.id), f.file_name))}>{f.file_name}</button>{canManage && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void perform(async token => { const result = await api.extract(token, row, companyId, f.id); if (mounted.current) { setProposal(result); setPrice(result.price_rub ?? ""); setBasis(result.price_basis); setDays(result.lead_time_days == null ? "" : String(result.lead_time_days)); setDelivery(result.delivery_date ?? ""); dirty.current = true; } })}>Разобрать с ИИ</button>}</li>)}</ul>}
        {proposal && <details open className="supplier-extraction"><summary>Данные из файла</summary>{proposal.warnings.map(w => <p className="hint" key={w}>{w}</p>)}{[proposal.price_evidence, proposal.lead_time_evidence, proposal.date_evidence].filter(Boolean).map((excerpt, i) => <blockquote key={`${i}:${excerpt}`}>{excerpt}</blockquote>)}</details>}
        <form className="supplier-quote" onSubmit={saveQuote} onChange={() => { dirty.current = true; }}><label>Цена, ₽<input aria-label="Цена из ответа, ₽" type="text" inputMode="decimal" pattern="[0-9]+([.,][0-9]{1,12})?" value={price} disabled={busy || !canManage} onChange={e => setPrice(e.target.value)} placeholder="Не указана" /></label><label>Цена относится к<select value={basis} disabled={busy || !canManage} onChange={e => setBasis(e.target.value as PriceBasis)}><option value="unknown">Нужно уточнить</option><option value="unit">Единице товара</option><option value="total">Всему запросу</option></select></label><div className="supplier-quote__dates"><label>Срок, дней<input type="number" min={0} max={3650} step={1} value={days} disabled={busy || !canManage} onChange={e => setDays(e.target.value)} /></label><div className="field"><label htmlFor={`supplier-delivery-${id}`}>Дата поставки</label><DateInput id={`supplier-delivery-${id}`} value={delivery} disabled={busy || !canManage} onValueChange={value => { dirty.current = true; setDelivery(value); }} /></div></div><label>Заметка для вашей компании<textarea rows={2} maxLength={2000} value={note} disabled={busy || !canManage} onChange={e => setNote(e.target.value)} /></label>{canManage && <button className="btn btn-primary" disabled={busy}>Проверено, сохранить ответ</button>}</form>
        {row.quoted_price_rub != null && <p className="hint">Сохранено: {formatRub(row.quoted_price_rub)}{row.price_basis === "unit" ? " за единицу" : row.price_basis === "total" ? " за весь запрос" : " — основание цены не уточнено"}.</p>}
      </div>}
    </div>
  </section>;
}

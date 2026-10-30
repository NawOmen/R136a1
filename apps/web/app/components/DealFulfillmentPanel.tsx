"use client";
import MoneyInput from "./MoneyInput";
import { DateInput } from "./DateInput";
import { formatDate, formatDateTime } from "../lib/dates";

import { russianMessage } from "../lib/russianMessages";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import { FilePicker } from "./FilePicker";
import { FulfillmentCommand, FulfillmentRecord, FulfillmentState, fulfillmentApi, formatRub, marketplace } from "../lib/marketplace";

const names: Record<string, string> = { prepare: "Подготовка", production: "Производство", logistics: "Получение и тариф",
  shipment: "Отгрузка партии", receipt: "Получение партии", inspection: "Проверка партии", complete: "Завершение заказа",
  request: "Запрос возврата или отмены", decision: "Решение по запросу", return_complete: "Завершение возврата",
  dispute_response: "Ответ на расхождение", dispute_decision: "Решение по расхождению", message: "Сообщение",
  proposal: "Предложение изменения получения", proposal_decision: "Решение по предложению" };
const actionNames: Record<string, string> = {prepare: "Сохранить параметры отгрузки", production: "Начать производство", logistics: "Согласовать получение", shipment: "Записать отгрузку", receipt: "Записать получение партии", inspection: "Сохранить результат проверки", complete: "Завершить заказ", request: "Отправить запрос", decision: "Сохранить решение", return_complete: "Подтвердить возврат", dispute_response: "Отправить ответ на расхождение", dispute_decision: "Сохранить решение по расхождению", message: "Отправить сообщение", proposal: "Предложить изменение получения", proposal_decision: "Сохранить решение по изменению"};
const statuses: Record<string, string> = { created: "Подготовка", in_production: "Производство", shipped: "Отгружено",
  partially_shipped: "Частично отгружено", partially_accepted: "Частично принято", disputed: "Открытое расхождение",
  delivered: "Получено и проверено", fulfilled: "Завершено", cancelled: "Отменено", returned: "Возвращено" };
const methodNames: Record<string, string> = { self_pickup: "Самовывоз", buyer_carrier: "Перевозчик покупателя", seller_delivery: "Согласованная доставка продавца" };
const eventStatuses: Record<string, string> = { pending: "Ожидает решения второй стороны", approved: "Согласовано, ожидается фактический возврат",
  confirmed: "Завершено", rejected: "Отклонено", open: "Ожидает ответа продавца", responded: "Ожидает решения покупателя", closed: "Закрыто" };
const today = () => new Date().toLocaleDateString("en-CA");

export default function DealFulfillmentPanel({ dealId, companyId, isBuyer, canManage, onRevision }: {
  dealId: string; companyId: string; isBuyer: boolean; canManage: boolean; onRevision: (n: number) => void;
}) {
  const [data, setData] = useState<FulfillmentState | null>(null);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true); const [pending, setPending] = useState(false);
  const [action, setAction] = useState("message"); const [fields, setFields] = useState<Record<string, string>>({ expected_date: today(), method: "self_pickup", kind: isBuyer ? "return" : "cancellation", resolution: "credit", approved: "true" });
  const [approved, setApproved] = useState(false); const [materials, setMaterials] = useState<{id: string; filename: string}[]>([]);
  const [rating, setRating] = useState("5"); const [review, setReview] = useState("");
  const alive = useRef(false); const generation = useRef(0); const busy = useRef(false);
  const retryCommand = useRef<{ fingerprint: string; command: FulfillmentCommand } | null>(null);
  const f = (key: string) => fields[key] ?? "";
  const change = (key: string, value: string) => { setFields(old => ({ ...old, [key]: value })); setApproved(false); };
  const reload = useCallback(async () => {
    const token = getToken(); if (!token) throw new Error("Войдите в аккаунт.");
    const seq = ++generation.current; setLoading(true);
    try {
      const value = await fulfillmentApi.get(token, dealId, companyId);
      if (alive.current && seq === generation.current) { setData(value); onRevision(value.revision); }
    } finally { if (alive.current && seq === generation.current) setLoading(false); }
  }, [dealId, companyId, onRevision]);
  useEffect(() => { alive.current = true; void reload().catch(e => { if (alive.current) setError(e.message); });
    return () => { alive.current = false; generation.current++; }; }, [reload]);
  async function perform(work: (token: string) => Promise<void>) {
    if (busy.current) return;
    const token = getToken(); if (!token) { setError("Войдите в аккаунт."); return; }
    busy.current = true; setPending(true); setError(""); setNotice("");
    try { await work(token); } catch (e) { if (alive.current) setError(e instanceof Error ? russianMessage(e.message) : "Действие не выполнено."); }
    finally { busy.current = false; if (alive.current) setPending(false); }
  }
  function payload(): Record<string, unknown> {
    const value: Record<string, unknown> = { note: f("note"), attachments: materials.map(m => m.id) };
    if (["prepare", "production", "logistics", "proposal", "shipment", "receipt", "inspection", "complete"].includes(action)) value.expected_date = f("expected_date");
    if (action === "prepare") Object.assign(value, { address: f("address"), city: f("city"), region: f("region"), country: "RU", packaging: f("packaging"),
      weight_kg: Number(f("weight")), volume_m3: Number(f("volume")), places: Number(f("places")), restrictions: f("restrictions"), hazard_class: f("hazard") || null });
    if (["logistics", "proposal"].includes(action)) Object.assign(value, { method: f("method"), carrier: f("carrier"), cost_rub: f("cost") || null, manual_confirmation: f("manual") === "true" });
    if (action === "shipment") Object.assign(value, { batch: f("batch"), units: Number(f("units")) });
    if (["receipt", "inspection"].includes(action)) Object.assign(value, { batch_id: f("batch_id"), line_id: data?.line_id });
    if (action === "receipt") Object.assign(value, { received: Number(f("received")), missing: Number(f("missing")) });
    if (action === "inspection") Object.assign(value, { accepted: Number(f("accepted")), rejected: Number(f("rejected")) });
    if (action === "request") Object.assign(value, { kind: f("kind"), units: Number(f("units")) });
    if (["decision", "return_complete"].includes(action)) value.event_id = f("event_id");
    if (["dispute_response", "dispute_decision"].includes(action)) value.dispute_id = f("dispute_id");
    if (action === "dispute_response") value.resolution = f("resolution");
    if (["decision", "dispute_decision", "proposal_decision"].includes(action)) value.approved = f("approved") === "true";
    if (action === "return_complete") value.restock_accepted = f("restock") === "true";
    if (action === "proposal_decision") value.proposal_id = f("proposal_id");
    return value;
  }
  function submit(e: FormEvent) {
    e.preventDefault(); if (!data || !approved) return;
    const body = payload(); const fingerprint = JSON.stringify({ action, body, companyId, dealId });
    if (retryCommand.current?.fingerprint !== fingerprint) retryCommand.current = { fingerprint, command: {
      action, payload: body, company_id: companyId, terms_version: data.terms_version, expected_revision: data.revision,
      human_approved: true, idempotency_key: crypto.randomUUID(),
    } };
    const command = retryCommand.current.command;
    void perform(async token => {
      const result = await fulfillmentApi.act(token, dealId, command);
      if (!alive.current) return;
      setData(result); onRevision(result.revision); retryCommand.current = null; setMaterials([]); setApproved(false); setAction("message");
      setFields(old => ({ ...old, note: "" })); setNotice("Действие записано. Количества и история обновлены.");
    });
  }
  function choose(next: string, key?: string, id?: string) {
    setAction(next); setApproved(false); if (key && id) setFields(old => ({ ...old, [key]: id }));
  }
  async function download(id: string) {
    await perform(async token => { const blob = await fulfillmentApi.download(token, dealId, companyId, id);
      if (!alive.current) return; const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = "Материал сделки"; link.click(); URL.revokeObjectURL(url); });
  }
  const files = (record: FulfillmentRecord) => record.attachments?.map((id, i) => <button type="button" className="btn btn-secondary btn-sm" key={id} disabled={pending} onClick={() => void download(id)}>Материал {i + 1}</button>);
  const input = (key: string, label: string, type = "text", required = true) => <div className="field"><label htmlFor={`fulfillment-${key}`}>{label}</label>{type === "date" ? <DateInput id={`fulfillment-${key}`} required={required} value={f(key)} onValueChange={value => change(key, value)} /> : key === "cost" ? <MoneyInput id={`fulfillment-${key}`} required={required} value={f(key)} min="0" onChange={e => change(key, e.target.value)} /> : <input id={`fulfillment-${key}`} type={type} required={required} value={f(key)} min={type === "number" ? "0" : undefined} step={type === "number" ? "any" : undefined} maxLength={type === "text" ? 500 : undefined} onChange={e => change(key, e.target.value)} />}</div>;
  const options = data ? ["message", ...(canManage ? [!isBuyer && !data.dispatch && !data.batches.length && "prepare", !isBuyer && data.stages.prepare && !data.stages.production && "production",
    isBuyer && !data.logistics && "logistics", !isBuyer && data.stages.production && data.logistics?.confirmed && data.totals.unshipped_units > 0 && "shipment",
    isBuyer && data.batches.some(b => b.units > b.received + b.missing) && "receipt", isBuyer && data.batches.some(b => b.received > b.inspected) && "inspection",
    isBuyer && !data.completed && data.totals.open_units === 0 && "complete", (data.totals.unshipped_units > 0 || (isBuyer && data.totals.net_units > 0)) && "request", data.requests.some(r => r.status === "pending" && r.company_id !== companyId) && "decision", !isBuyer && data.requests.some(r => r.status === "approved") && "return_complete",
    !isBuyer && data.disputes.some(d => d.status !== "closed") && "dispute_response", isBuyer && data.disputes.some(d => d.status === "responded") && "dispute_decision", data.dispatch && !data.batches.length && !data.proposals.some(p => p.status === "pending") && "proposal", data.proposals.some(p => p.status === "pending" && p.company_id !== companyId) && "proposal_decision"] : [])].filter((v): v is string => typeof v === "string") : [];
  return <section className="card" aria-busy={pending || loading}><h2>Исполнение по партиям</h2>
    {error && <div className="alert alert-error" role="alert">{error}<button type="button" className="btn btn-secondary" disabled={pending || loading} onClick={() => { retryCommand.current = null; void perform(async () => { await reload(); }); }}>Обновить сделку</button></div>}
    {notice && <p className="alert alert-success" role="status">{notice}</p>}
    {loading && <p role="status">Загружаем исполнение…</p>}
    {data && <><p><b>{statuses[data.status] ?? "Исполнение"}</b> · согласованные условия, версия {data.terms_version}</p>
      <dl className="stats-grid">{Object.entries({ Заказано: data.totals.ordered_units, Отгружено: data.totals.shipped_units, Получено: data.totals.received_units,
        Принято: data.totals.accepted_units, Возвращено: data.totals.returned_units, Отменено: data.totals.cancelled_units, "Открытые обязательства": data.totals.open_units }).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
      <p className="hint">Спорный объём не считается принятым. Возврат не создаёт новый заказ.</p>
      <dl className="readable-facts">
        <div><dt>Согласованная стоимость заказа продавца</dt><dd>{formatRub(data.commercial.seller_total_rub)}</dd></div>
        <div><dt>В том числе доставка продавца</dt><dd>{data.commercial.seller_delivery_rub == null ? "Не определена" : formatRub(data.commercial.seller_delivery_rub)}</dd></div>
        <div><dt>Перевозчик покупателя / самовывоз отдельно</dt><dd>{data.commercial.external_carrier_rub == null ? "Тариф неизвестен" : formatRub(data.commercial.external_carrier_rub)}</dd></div>
      </dl>
      <h3>Получение внутри России</h3><p>Адрес покупателя: {data.destination ?? "Не указан"}</p>
      {data.dispatch ? <>
        <dl className="readable-facts">
          <div><dt>Отгрузка</dt><dd>{data.dispatch.address}, {data.dispatch.city}, {data.dispatch.region}</dd></div>
          <div><dt>Готовность</dt><dd>{formatDate(data.dispatch.expected_date)}</dd></div>
          <div><dt>Упаковка и груз</dt><dd>{data.dispatch.packaging} · {data.dispatch.places} мест · {data.dispatch.weight_kg} кг · {data.dispatch.volume_m3} м³</dd></div>
          <div><dt>Ограничения</dt><dd>{data.dispatch.restrictions || "Не указаны"}</dd></div>
          <div><dt>Класс опасности</dt><dd>{data.dispatch.hazard_class ?? "Не указан"}</dd></div>
        </dl>
        <p className="hint">{data.dispatch.classification_note}</p>
      </> : <p className="hint">Продавец должен подтвердить параметры подготовки и адрес отгрузки.</p>}
      {data.logistics ? <p>{methodNames[data.logistics.method]}, {data.logistics.carrier || "без отдельного перевозчика"}. Срок: {formatDate(data.logistics.expected_date)}. Тариф: <b>{data.logistics.cost_rub == null ? "Неизвестен — финальное согласие недоступно" : formatRub(data.logistics.cost_rub)}</b>. {data.logistics.confirmed ? "Согласовано" : "Требуется согласие продавца"}.</p> : <p className="hint">Тариф пока неизвестен. До согласования получения отгрузка недоступна.</p>}
      <ul className="reading-list hint"><li>Стоимость перевозки — отдельно от товаров. ПоРукам не перевозчик и не подтверждает оплату.</li><li>Опасный груз и объём 12–15 м³ требуют ручного уточнения. Размер партии не гарантирует наличие транспорта.</li></ul>
      <h3>Партии</h3>{!data.batches.length && <p className="hint">Отгрузок пока нет.</p>}
      {data.batches.map(b => <div className="alert" key={b.id}><b>{b.batch}</b>: отгружено {b.units}, получено {b.received}, принято {b.accepted}, отклонено {b.rejected}, не поставлено {b.missing}.<p>Ожидаемая дата: {formatDate(b.expected_date, "Историческая партия")}; факт: {b.actual_date ? formatDateTime(b.actual_date) : "Ранее подтверждено"}.</p>{files(b)}{canManage && isBuyer && <><button type="button" className="btn btn-secondary btn-sm" onClick={() => choose("receipt", "batch_id", b.id)}>Записать получение</button><button type="button" className="btn btn-secondary btn-sm" onClick={() => choose("inspection", "batch_id", b.id)}>Проверить полученное</button></>}</div>)}
      <h3>Расхождения</h3>{!data.disputes.length && <p className="hint">Расхождений нет.</p>}{data.disputes.map(d => <div className="alert" key={d.id}><b>{eventStatuses[d.status ?? "open"]}</b> · {d.units} ед. · условия версии {d.terms_version}<p>{d.note}</p>{files(d)}{d.responses?.map(response => <p key={response.id}>Ответ продавца: {response.note}. Предложено: {response.resolution === "accept" ? "Принять после проверки" : "Уменьшить обязательство и стоимость товара"}{files(response)}</p>)}{canManage && d.status !== "closed" && (!isBuyer || d.status === "responded") && <button type="button" className="btn btn-secondary" onClick={() => choose(isBuyer ? "dispute_decision" : "dispute_response", "dispute_id", d.id)}>{isBuyer ? "Решение покупателя" : "Ответить на расхождение"}</button>}</div>)}
      <h3>Возвраты и отмены</h3>{!data.requests.length && <p className="hint">Запросов нет.</p>}{data.requests.map(r => <div className="alert" key={r.id}><b>{r.kind === "return" ? "Возврат" : "Отмена остатка"}: {r.units} ед.</b> · {eventStatuses[r.status ?? "pending"]}<p>{r.note}</p>{files(r)}{canManage && r.company_id !== companyId && r.status === "pending" && <button type="button" className="btn btn-secondary" onClick={() => choose("decision", "event_id", r.id)}>Согласовать или отклонить</button>}{canManage && !isBuyer && r.status === "approved" && <button type="button" className="btn btn-secondary" onClick={() => choose("return_complete", "event_id", r.id)}>Подтвердить фактический возврат</button>}</div>)}
      <h3>Предложения изменения условий</h3>{!data.proposals.length && <p className="hint">Изменений нет. Сообщение само по себе не меняет обязательства.</p>}{data.proposals.map(p => <div className="alert" key={p.id}><b>{eventStatuses[p.status ?? "pending"] ?? "Согласовано"}</b> · версия {p.terms_version}<p>{p.note}</p><p>{methodNames[p.method ?? ""]}; перевозчик: {p.carrier || "Не требуется"}; срок: {formatDate(p.expected_date)}; тариф: {p.cost_rub == null ? "Неизвестен" : formatRub(p.cost_rub)}. Текущие условия показаны в разделе получения выше.</p>{files(p)}{canManage && p.status === "pending" && p.company_id !== companyId && <button type="button" className="btn btn-secondary" onClick={() => choose("proposal_decision", "proposal_id", p.id)}>Рассмотреть изменение</button>}</div>)}
      <h3>Переписка по сделке</h3>{!data.messages.length && <p className="hint">Сообщений пока нет.</p>}{data.messages.map(m => <p key={m.id}><b>{m.company_id === companyId ? "Ваша компания" : "Другая сторона"}</b> · версия {m.terms_version}<br />{m.note}<br />{files(m)}</p>)}
      <form onSubmit={submit}><fieldset disabled={pending} className="form-grid" style={{border:0, padding:0, margin:0, minWidth:0}}><div className="field"><label htmlFor="fulfillment-action">Действие</label><select id="fulfillment-action" value={action} onChange={e => choose(e.target.value)}>{Array.from(new Set([action, ...options])).map(v => <option key={v} value={v}>{names[v]}</option>)}</select></div>
        {["prepare", "production", "logistics", "proposal", "shipment", "receipt", "inspection", "complete"].includes(action) && input("expected_date", "Ожидаемая дата этапа", "date")}
        {action === "prepare" && <>{input("address", "Адрес отгрузки в России")}{input("city", "Город")}{input("region", "Регион")}{input("packaging", "Упаковка")}{input("weight", "Вес, кг", "number")}{input("volume", "Объём, м³", "number")}{input("places", "Количество мест", "number")}{input("restrictions", "Особые ограничения", "text", false)}<div className="field"><label>Класс опасности по документам<select value={f("hazard")} onChange={e => change("hazard", e.target.value)}><option value="">Не относится к опасным грузам</option>{[1,2,3,4,5,6,7,8,9].map(n => <option key={n} value={n}>{n}</option>)}</select></label></div></>}
        {["logistics", "proposal"].includes(action) && <><div className="field"><label>Способ получения<select value={f("method")} onChange={e => change("method", e.target.value)}>{Object.entries(methodNames).map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label></div>{input("carrier", "Перевозчик", "text", f("method") === "buyer_carrier")}{input("cost", "Подтверждённый тариф, ₽ (0 — без платы)", "number")}<label><input type="checkbox" checked={f("manual") === "true"} onChange={e => change("manual", String(e.target.checked))} /> Ограничения груза и условия перевозки уточнены вручную</label></>}
        {action === "shipment" && <>{input("batch", "Название или номер партии")}{input("units", "Количество отгрузки", "number")}</>}
        {["receipt", "inspection"].includes(action) && <div className="field"><label>Партия<select required value={f("batch_id")} onChange={e => change("batch_id", e.target.value)}><option value="">Выберите партию</option>{data.batches.map(b => <option key={b.id} value={b.id}>{b.batch}</option>)}</select></label></div>}
        {action === "receipt" && <>{input("received", "Фактически получено", "number")}{input("missing", "Не поставлено из этой партии", "number")}</>}
        {action === "inspection" && <>{input("accepted", "Принято после проверки", "number")}{input("rejected", "Отклонено, требуется решение", "number")}</>}
        {action === "request" && <><div className="field"><label>Запрос<select value={f("kind")} onChange={e => change("kind", e.target.value)}>{isBuyer && <option value="return">Возврат принятого товара</option>}<option value="cancellation">Отмена неотгруженного остатка</option></select></label></div>{input("units", "Количество", "number")}</>}
        {["decision", "return_complete"].includes(action) && <div className="field"><label>Запрос<select value={f("event_id")} required onChange={e => change("event_id", e.target.value)}><option value="">Выберите запрос</option>{data.requests.filter(r => r.company_id !== companyId && r.status === (action === "decision" ? "pending" : "approved")).map(r => <option key={r.id} value={r.id}>{r.kind === "return" ? "Возврат" : "Отмена"} {r.units} ед. — {r.note}</option>)}</select></label></div>}
        {["dispute_response", "dispute_decision"].includes(action) && <div className="field"><label>Расхождение<select value={f("dispute_id")} required onChange={e => change("dispute_id", e.target.value)}><option value="">Выберите расхождение</option>{data.disputes.filter(d => d.status !== "closed").map(d => <option key={d.id} value={d.id}>{d.units} ед. — {d.note}</option>)}</select></label></div>}
        {action === "dispute_response" && <div className="field"><label>Предложение продавца<select value={f("resolution")} onChange={e => change("resolution", e.target.value)}><option value="credit">Уменьшить обязательство и стоимость товара</option><option value="accept">Принять после устранения расхождения и проверки</option></select></label></div>}
        {action === "proposal_decision" && <div className="field"><label>Предложение<select value={f("proposal_id")} required onChange={e => change("proposal_id", e.target.value)}><option value="">Выберите предложение</option>{data.proposals.filter(p => p.status === "pending" && p.company_id !== companyId).map(p => <option key={p.id} value={p.id}>{p.note}</option>)}</select></label></div>}
        {["decision", "dispute_decision", "proposal_decision"].includes(action) && <div className="field"><label>Решение<select value={f("approved")} onChange={e => change("approved", e.target.value)}><option value="true">Согласовать</option><option value="false">Отклонить</option></select></label></div>}
        {action === "return_complete" && <label><input type="checkbox" checked={f("restock") === "true"} onChange={e => change("restock", String(e.target.checked))} /> Товар получен, качество проверено: разрешаю возврат на доступный склад</label>}
        <div className="field"><label htmlFor="fulfillment-note">{action === "message" ? "Сообщение" : "Основание, доказательство или номер акта"}</label><textarea id="fulfillment-note" required minLength={3} maxLength={1000} value={f("note")} onChange={e => change("note", e.target.value)} /></div>
        <div className="field"><label htmlFor="fulfillment-file">Материалы (PDF, PNG, JPEG до 10 МБ)</label><FilePicker id="fulfillment-file" accept="application/pdf,image/png,image/jpeg" disabled={pending || materials.length >= 10} status={pending ? "Обрабатываем файл…" : materials.length ? `Прикреплено файлов: ${materials.length}` : "Файл не выбран"} onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; void perform(async token => { const item = await fulfillmentApi.upload(token, dealId, companyId, data.terms_version, file); if (alive.current) { setMaterials(old => [...old, item]); setApproved(false); } }); }} />{materials.map(m => <span key={m.id}>{m.filename} <button type="button" disabled={pending} onClick={() => { setMaterials(old => old.filter(v => v.id !== m.id)); setApproved(false); }}>Убрать</button></span>)}</div>
        <label><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} required /> {action === "message" ? "Подтверждаю отправку в эту сделку" : "Подтверждаю действие, количество и основание от имени компании"}</label>
        <button className="btn btn-primary" disabled={pending || !approved || (!canManage && action !== "message")}>{pending ? "Сохраняем…" : actionNames[action]}</button>
      </fieldset></form>
      <details><summary>Полная история этапов и решений</summary>{data.history.map(h => <p key={h.id}><b>{names[h.action ?? ""]}</b> · условия версии {h.terms_version} · план {formatDate(h.expected_date, "Не применимо")} · факт {h.actual_date ? formatDateTime(h.actual_date) : "—"}<br />{h.note}{files(h)}</p>)}</details>
      <p className="hint">{data.rating_rule}</p>
      {data.totals.net_units > 0 && data.totals.open_units === 0 && canManage && <form onSubmit={e => { e.preventDefault(); void perform(async token => { await marketplace.createReview(token, dealId, companyId, Number(rating), review); if (alive.current) { setReview(""); setNotice("Отзыв опубликован по подтверждённой сделке."); } }); }}><h3>Отзыв по исполнению</h3><div className="field"><label>Оценка<select value={rating} onChange={e => setRating(e.target.value)}>{[5,4,3,2,1].map(n => <option key={n}>{n}</option>)}</select></label></div><div className="field"><label>Комментарий<textarea required minLength={10} maxLength={2000} value={review} onChange={e => setReview(e.target.value)} /></label></div><button className="btn btn-primary" disabled={pending}>Опубликовать отзыв</button></form>}
    </>}
  </section>;
}

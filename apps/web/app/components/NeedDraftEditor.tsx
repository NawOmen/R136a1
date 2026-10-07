"use client";

import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { DeliveryAddress, marketplace, Need, PRODUCT_CATEGORY_TREE } from "../lib/marketplace";

export default function NeedDraftEditor({ need, onSaved }: { need: Need; onSaved: (need: Need) => void }) {
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(need.category);
  const [quantity, setQuantity] = useState(String(need.volume_units));
  const [budget, setBudget] = useState(need.budget_rub == null ? "" : String(need.budget_rub));
  const [deadline, setDeadline] = useState(need.deadline_date);
  const [validUntil, setValidUntil] = useState(need.valid_until ?? need.deadline_date);
  const [address, setAddress] = useState(need.delivery_address_id ?? "");
  const [visibility, setVisibility] = useState(need.visibility);
  const [addresses, setAddresses] = useState<DeliveryAddress[]>([]);
  const [rows, setRows] = useState(Object.entries(need.characteristics).map(([key, value]) => ({ key, value: typeof value === "object" ? JSON.stringify(value) : String(value), original: value })));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const token = getToken(); if (!token) return;
    let cancelled = false;
    marketplace.getAddresses(token, need.company_id).then(data => { if (!cancelled) setAddresses(data); }).catch(() => { if (!cancelled) setError("Не удалось загрузить адреса. Обновите страницу."); });
    return () => { cancelled = true; };
  }, [need.company_id]);

  async function save(event: FormEvent) {
    event.preventDefault(); const token = getToken(); if (!token || saving) return;
    const characteristics: Record<string, unknown> = {};
    for (const row of rows) {
      const key = row.key.trim();
      if (!key || !row.value.trim() || Object.hasOwn(characteristics, key)) { setError("Заполните характеристики без повторяющихся названий."); return; }
      const initial = typeof row.original === "object" ? JSON.stringify(row.original) : String(row.original);
      characteristics[key] = row.value === initial ? row.original : row.value.trim();
    }
    setSaving(true); setError("");
    try {
      onSaved(await marketplace.editNeed(token, need.id, {
        company_id: need.company_id, expected_revision: need.revision, category, characteristics,
        volume_units: Number(quantity), budget_rub: budget ? Number(budget) : null,
        deadline_date: deadline, valid_until: validUntil, delivery_address_id: address || null, visibility,
      }));
      setEditing(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось сохранить черновик."); }
    finally { setSaving(false); }
  }
  if (!editing) return <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>Изменить черновик</button>;
  return <form onSubmit={save} className="form-grid">
    <p className="hint">Изменения сохраняются в этой потребности. Вложения сохранятся. Версия: {need.revision}.</p>
    {error && <div role="alert" className="alert alert-error">{error}</div>}
    <fieldset disabled={saving}>
      <div className="field"><label htmlFor="edit-category">Категория</label><select id="edit-category" value={category} onChange={e => setCategory(e.target.value)}>{Array.from(new Set([need.category, ...Object.keys(PRODUCT_CATEGORY_TREE)])).map(item => <option key={item}>{item}</option>)}</select></div>
      {rows.map((row, index) => <div className="field" key={index}>
        <input aria-label={`Название характеристики ${index + 1}`} required maxLength={120} value={row.key} onChange={e => setRows(rows.map((item, i) => i === index ? { ...item, key: e.target.value } : item))} />
        <input aria-label={`Значение характеристики ${index + 1}`} required value={row.value} readOnly={typeof row.original === "object" && row.original !== null} onChange={e => setRows(rows.map((item, i) => i === index ? { ...item, value: e.target.value } : item))} />
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRows(rows.filter((_, i) => i !== index))}>Удалить характеристику</button>
      </div>)}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRows([...rows, { key: "", value: "", original: "" }])}>Добавить характеристику</button>
      <div className="field"><label htmlFor="edit-quantity">Количество единиц</label><input id="edit-quantity" required type="number" min="1" step="1" value={quantity} onChange={e => setQuantity(e.target.value)} /></div>
      <div className="field"><label htmlFor="edit-budget">Бюджет, ₽</label><input id="edit-budget" type="number" min="0.01" step="0.01" value={budget} onChange={e => setBudget(e.target.value)} /></div>
      <div className="field"><label htmlFor="edit-deadline">Срок поставки</label><input id="edit-deadline" type="date" required value={deadline} onChange={e => setDeadline(e.target.value)} /></div>
      <div className="field"><label htmlFor="edit-valid">Актуально до</label><input id="edit-valid" type="date" required value={validUntil} onChange={e => setValidUntil(e.target.value)} /></div>
      <div className="field"><label htmlFor="edit-address">Адрес доставки</label><select id="edit-address" value={address} onChange={e => setAddress(e.target.value)}><option value="">Не указан</option>{addresses.map(item => <option key={item.id} value={item.id}>{item.address}</option>)}</select></div>
      <div className="field"><label htmlFor="edit-visibility">Видимость</label><select id="edit-visibility" value={visibility} onChange={e => setVisibility(e.target.value as Need["visibility"])}><option value="open_anonymized">Открытая (анонимизированная)</option><option value="closed">Закрытая</option>{visibility === "selected_producers" && <option value="selected_producers">Для выбранных производителей</option>}</select></div>
      <div className="actions"><button className="btn btn-primary">{saving ? "Сохраняем…" : "Сохранить изменения"}</button><button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>Отмена</button></div>
    </fieldset>
  </form>;
}

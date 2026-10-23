"use client";
import { CharacteristicValue } from "./CharacteristicValue";
import { DateInput } from "./DateInput";

import { canonicalCharacteristicKey } from "../lib/categoryProfiles";
import { russianMessage } from "../lib/russianMessages";
import { russianLabel, displayValue, fieldName } from "../lib/presentation";
import CharacteristicSuggestions from "./CharacteristicSuggestions";
import PhysicalQuantityReview from "./PhysicalQuantityReview";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { DeliveryAddress, marketplace, Need, NeedEditImpact, PRODUCT_CATEGORY_TREE } from "../lib/marketplace";

export default function NeedDraftEditor({ need, onSaved }: { need: Need; onSaved: (need: Need) => void }) {
  const [quantityApproved, setQuantityApproved] = useState(false);
  const [editing, setEditing] = useState(false);
  const [subcategory, setSubcategory] = useState(need.subcategory ?? "");
  const [category, setCategory] = useState(need.category);
  const [quantity, setQuantity] = useState(String(need.volume_units));
  const [budget, setBudget] = useState(need.budget_rub == null ? "" : String(need.budget_rub));
  const [deadline, setDeadline] = useState(need.deadline_date);
  const [validUntil, setValidUntil] = useState(need.valid_until ?? need.deadline_date);
  const [address, setAddress] = useState(need.delivery_address_id ?? "");
  const [visibility, setVisibility] = useState(need.visibility);
  const [addresses, setAddresses] = useState<DeliveryAddress[]>([]);
  const [rows, setRows] = useState(Object.entries(need.characteristics).map(([key, value]) => ({ key, value: typeof value === "boolean" ? displayValue(value) : typeof value === "object" ? JSON.stringify(value) : String(value), original: value })));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [impact, setImpact] = useState<NeedEditImpact | null>(null);
  const [impactApproved, setImpactApproved] = useState(false);
  useEffect(() => { setImpact(null); setImpactApproved(false); }, [category, subcategory, rows, quantity, budget, deadline, validUntil, address, visibility]);
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
      const initial = typeof row.original === "boolean" ? displayValue(row.original) : typeof row.original === "object" ? JSON.stringify(row.original) : String(row.original);
      characteristics[key] = row.value === initial ? row.original : typeof row.original === "boolean" && ["да", "нет"].includes(row.value.trim().toLowerCase()) ? row.value.trim().toLowerCase() === "да" : row.value.trim();
    }
    setSaving(true); setError("");
    try {
      const input = {
        quantity_conversion_approved: quantityApproved,
        company_id: need.company_id, expected_revision: need.revision, category, subcategory, characteristics,
        volume_units: Number(quantity), budget_rub: budget ? String(budget) : null,
        deadline_date: deadline, valid_until: validUntil, delivery_address_id: address || null, visibility,
      };
      if (need.status !== "draft" && !impact) {
        const preview = await marketplace.previewNeedEdit(token, need.id, input);
        setImpact(preview);
        if (!preview.editable) setError("По этой версии уже созданы обязательства. Измените условия через согласование сделки.");
        return;
      }
      if (impact?.requires_confirmation && !impactApproved) { setError("Подтвердите последствия изменения."); return; }
      onSaved(await marketplace.editNeed(token, need.id, { ...input, impact_hash: impact?.impact_hash }));
      setEditing(false);
    } catch (reason) { setError(reason instanceof Error ? russianMessage(reason.message) : "Не удалось сохранить черновик."); }
    finally { setSaving(false); }
  }
  if (!editing) return <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>{need.status === "draft" ? "Изменить черновик" : "Изменить спецификацию"}</button>;
  return <form onSubmit={save} className="form-grid">
    <p className="hint">Изменения сохраняются новой версией этой потребности. Вложения сохранятся. Версия: {need.revision}.</p>
    {error && <div role="alert" className="alert alert-error">{error}</div>}
    <fieldset disabled={saving}>
      <div className="field"><label htmlFor="edit-category">Категория</label><select id="edit-category" value={category} onChange={e => { setCategory(e.target.value); setSubcategory(""); }}>{Array.from(new Set([need.category, ...Object.keys(PRODUCT_CATEGORY_TREE)])).map(item => <option key={item}>{item}</option>)}</select></div>
      <div className="field"><label htmlFor="edit-subcategory">Подкатегория</label><select id="edit-subcategory" required value={subcategory} onChange={e => setSubcategory(e.target.value)}><option value="">Выберите подкатегорию</option>{(PRODUCT_CATEGORY_TREE[category] ?? []).map(item => <option key={item}>{item}</option>)}</select></div>
      <CharacteristicSuggestions category={category} subcategory={subcategory} keys={rows.map(row => row.key)} onAdd={key => setRows([...rows, {key,value:"",original:""}])} />
      {rows.map((row, index) => <div className="field" key={index}>
        <input aria-label={`Название характеристики ${index + 1}`} required maxLength={120} value={fieldName(row.key)} onChange={e => setRows(rows.map((item, i) => i === index ? { ...item, key: canonicalCharacteristicKey(e.target.value) } : item))} />
        {typeof row.original === "object" && row.original !== null ? <input aria-label={`Значение характеристики ${index + 1}`} readOnly value={row.value} /> : <CharacteristicValue category={category} subcategory={subcategory} fieldKey={row.key} value={row.value} label={`Значение характеристики ${index + 1}`} onChange={value => setRows(rows.map((item, i) => i === index ? { ...item, value } : item))} />}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRows(rows.filter((_, i) => i !== index))}>Удалить характеристику</button>
      </div>)}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRows([...rows, { key: "", value: "", original: "" }])}>Добавить характеристику</button>
      <div className="field"><label htmlFor="edit-quantity">Количество единиц</label><input id="edit-quantity" required type="number" min="0.000001" step="any" value={quantity} onChange={e => setQuantity(e.target.value)} /></div>
      <div className="field"><label htmlFor="edit-budget">Бюджет, ₽</label><input id="edit-budget" type="number" min="0.01" step="0.01" value={budget} onChange={e => setBudget(e.target.value)} /></div>
      <div className="field"><label htmlFor="edit-deadline">Срок поставки</label><DateInput id="edit-deadline" required value={deadline} onValueChange={e => setDeadline(e)} /></div>
      <div className="field"><label htmlFor="edit-valid">Актуально до</label><DateInput id="edit-valid" required value={validUntil} onValueChange={e => setValidUntil(e)} /></div>
      <div className="field"><label htmlFor="edit-address">Адрес доставки</label><select id="edit-address" value={address} onChange={e => setAddress(e.target.value)}><option value="">Не указан</option>{addresses.map(item => <option key={item.id} value={item.id}>{item.address}</option>)}</select></div>
      <div className="field"><label htmlFor="edit-visibility">Видимость</label><select id="edit-visibility" value={visibility} onChange={e => setVisibility(e.target.value as Need["visibility"])}><option value="open_anonymized">Открытая (анонимизированная)</option>{visibility === "closed" && <option value="closed">Закрытая — сохранённый запрос</option>}{visibility === "selected_producers" && <option value="selected_producers">Для выбранных производителей</option>}</select></div>
      <PhysicalQuantityReview kind="need" values={{ characteristics: Object.fromEntries(rows.filter(row => row.key.trim()).map(row => [row.key.trim(), row.value])), volume_units: quantity }} approved={quantityApproved} onApproval={setQuantityApproved} />
      {impact && <section aria-label="Последствия изменения">
        <h3>Что изменится</h3>
        {Object.entries(impact.changes).map(([key, diff]) => <p key={key}>{({ category: "Категория", subcategory: "Подкатегория", characteristics: "Характеристики", volume_units: "Количество", budget_rub: "Бюджет", deadline_date: "Срок поставки", valid_until: "Актуальность", delivery_address_id: "Адрес доставки", evidence: "Подтверждение требований" } as Record<string, string>)[key] ?? russianLabel(key)}: {displayValue(diff.before)} → {displayValue(diff.after)}</p>)}
        <p>Потребуют пересчёта: КП — {impact.affected.offers.length}; черновики КП — {impact.affected.offer_drafts.length}; группы — {impact.affected.coalitions.length}; ресурсные планы — {impact.affected.resource_plans.length}; варианты подбора — {impact.affected.optimization_variants.length}. Участники получат уведомления, прежние условия сохранятся в истории.</p>
        {impact.requires_confirmation && <label><input type="checkbox" checked={impactApproved} onChange={event => setImpactApproved(event.target.checked)} />Подтверждаю новые требования и отмену прежних предварительных согласий</label>}
      </section>}
      <div className="actions"><button className="btn btn-primary" disabled={impact?.editable === false || (impact?.requires_confirmation && !impactApproved)}>{saving ? "Сохраняем…" : need.status !== "draft" && !impact ? "Предпросмотр изменений" : "Сохранить изменения"}</button><button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>Отмена</button></div>
    </fieldset>
  </form>;
}

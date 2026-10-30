"use client";
import MoneyInput from "./MoneyInput";
import { useEffect, useRef, useState } from "react";
import { DateInput } from "./DateInput";
import { Icon } from "./Icon";
import { getToken } from "../lib/api";
import { ApiError, formatRub, marketplace, Need, NeedEditImpact } from "../lib/marketplace";
import { russianMessage } from "../lib/russianMessages";
import { formatDate } from "../lib/dates";

// Изменение потребности из списка: сначала показываем последствия правки
// (POST /needs/{id}/edit-preview), затем сохраняем новую версию (PUT).
// Правка не переписывает обязательства: если они уже есть, сервер откажет.

const FIELD_LABELS: Record<string, string> = {
  volume_units: "Количество",
  budget_rub: "Бюджет",
  deadline_date: "Срок поставки",
  valid_until: "Карточка актуальна до",
  visibility: "Кто увидит потребность",
  characteristics: "Характеристики",
  delivery_address_id: "Адрес доставки",
  category: "Категория",
  subcategory: "Вид товара",
};

function displayValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "budget_rub") return formatRub(value as string | number);
  if (field === "deadline_date" || field === "valid_until") return formatDate(String(value));
  if (field === "visibility") return value === "open_anonymized" ? "Открыта для подбора" : value === "closed" ? "Закрытая" : String(value);
  return String(value);
}

export function NeedEditDialog({ need, onSaved, onClose }: {
  need: Need;
  onSaved: (updated: Need) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [volumeUnits, setVolumeUnits] = useState(String(need.volume_units));
  const [budgetRub, setBudgetRub] = useState(need.budget_rub ? String(need.budget_rub) : "");
  const [deadlineDate, setDeadlineDate] = useState(need.deadline_date);
  const [validUntil, setValidUntil] = useState(need.valid_until ?? "");
  const [visibility, setVisibility] = useState(need.visibility);
  const [impact, setImpact] = useState<NeedEditImpact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close(); }, []);
  useEffect(() => { setImpact(null); }, [volumeUnits, budgetRub, deadlineDate, validUntil, visibility]);

  function payload(hash?: string) {
    return {
      company_id: need.company_id,
      category: need.category,
      subcategory: need.subcategory ?? null,
      characteristics: need.characteristics,
      volume_units: Number(volumeUnits),
      budget_rub: budgetRub ? budgetRub : null,
      deadline_date: deadlineDate,
      delivery_address_id: need.delivery_address_id,
      visibility,
      valid_until: validUntil || undefined,
      expected_revision: need.revision,
      ...(hash ? { impact_hash: hash } : {}),
    };
  }

  async function check() {
    const token = getToken();
    if (!token) { setError("Войдите, чтобы изменить потребность."); return; }
    if (!(Number(volumeUnits) > 0) || !deadlineDate) { setError("Укажите количество и срок поставки."); return; }
    setBusy(true); setError(null);
    try {
      setImpact(await marketplace.previewNeedEdit(token, need.id, payload()));
    } catch (err: unknown) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось проверить изменения.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    const token = getToken();
    if (!token || !impact) return;
    setBusy(true); setError(null);
    try {
      const updated = await marketplace.editNeed(token, need.id, payload(impact.requires_confirmation ? impact.impact_hash : undefined));
      onSaved(updated);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось сохранить изменения.");
    } finally {
      setBusy(false);
    }
  }

  const changes = impact ? Object.entries(impact.changes) : [];
  const ready = impact !== null && impact.editable && changes.length > 0;

  return <dialog ref={dialog} className="address-dialog need-edit-dialog" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }} onClick={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <div className="address-dialog__body">
      <div className="company-row">
        <div><p className="hint">{need.category}{need.subcategory ? ` · ${need.subcategory}` : ""}</p><h2>Изменить потребность</h2></div>
        <button type="button" className="icon-button" aria-label="Закрыть изменение потребности" disabled={busy} onClick={onClose}><Icon name="close" /></button>
      </div>
      <div className="need-form-grid need-commercial">
        <div className="field"><label htmlFor="edit-volume">Количество</label><input id="edit-volume" type="number" min="0.000001" step="any" value={volumeUnits} disabled={busy} onChange={event => setVolumeUnits(event.target.value)} required /></div>
        <div className="field"><label htmlFor="edit-budget">Бюджет, ₽</label><MoneyInput id="edit-budget" min="0.01" value={budgetRub} disabled={busy} onChange={event => setBudgetRub(event.target.value)} /></div>
        <div className="field"><label htmlFor="edit-deadline">Получить до</label><DateInput id="edit-deadline" value={deadlineDate} disabled={busy} onValueChange={setDeadlineDate} required /></div>
        <div className="field"><label htmlFor="edit-valid">Карточка актуальна до</label><DateInput id="edit-valid" value={validUntil} disabled={busy} onValueChange={setValidUntil} /></div>
      </div>
      <div className="field"><label htmlFor="edit-visibility">Кто увидит потребность</label><select id="edit-visibility" value={visibility} disabled={busy} onChange={event => setVisibility(event.target.value as Need["visibility"])}><option value="open_anonymized">Открыта для подбора производителям</option><option value="closed">Закрытая — только для адресных запросов</option></select></div>

      {impact && !impact.editable && <p className="alert alert-warning" role="status">По этой версии уже есть обязательства. Изменение требований проведите через согласованный процесс сделки.</p>}
      {impact && impact.editable && changes.length === 0 && <p className="hint" role="status">Условия не изменились — сохранять нечего.</p>}
      {changes.length > 0 && <>
        <p className="hint">Что изменится:</p>
        <ul className="company-list need-edit-changes">
          {changes.map(([field, value]) => <li key={field} className="company-meta">{FIELD_LABELS[field] ?? field}: было — {displayValue(field, value.before)}; станет — {displayValue(field, value.after)}</li>)}
        </ul>
      </>}
      {impact?.requires_confirmation && impact.editable && <p className="hint">На эту потребность опираются другие участники: подтвердите последствия изменения.</p>}

      {error && <p className="alert alert-error" role="alert">{error}</p>}
      <div className="actions">
        {!impact ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void check()}>{busy ? "Проверяем…" : "Проверить изменения"}</button>
          : <button type="button" className="btn btn-primary" disabled={busy || !ready} onClick={() => void save()}>{busy ? "Сохраняем…" : "Сохранить изменения"}</button>}
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>Отмена</button>
      </div>
    </div>
  </dialog>;
}

"use client";
import { useEffect, useState } from "react";
import { RuleValue } from "./CategoryPassportDetails";
import { getToken } from "../lib/api";
import { marketplace, ProfileRevisionPreview } from "../lib/marketplace";

export default function ProfileRevisionPanel({ kind, id, revision, draft, onAdopted }: {
  kind: "products" | "needs"; id: string; revision?: number; draft: boolean; onAdopted: () => Promise<void>;
}) {
  const [preview, setPreview] = useState<ProfileRevisionPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    setPreview(null); setError(null);
    if (!token) return;
    setLoading(true);
    marketplace.getProfileRevision(token, kind, id).then((value) => { if (!cancelled) setPreview(value); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : "Не удалось сравнить правила."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [kind, id, revision, retry]);
  async function adopt() {
    const token = getToken();
    if (!token || !preview || saving) return;
    setSaving(true); setError(null);
    try {
      await marketplace.adoptProfileRevision(token, kind, id, preview, revision);
      // Refresh the record first: a failed refresh must remain visible and retryable.
      await onAdopted(); setRetry((value) => value + 1);
    } catch (err) { setError(err instanceof Error ? err.message : "Не удалось принять правила."); }
    finally { setSaving(false); }
  }
  return <details className="card">
    <summary>Правила категории и обновления</summary>
    {loading && <p role="status" className="hint">Сравниваем правила…</p>}
    {error && <div role="alert" className="alert alert-error">{error} <button type="button" disabled={saving || loading} onClick={() => setRetry((value) => value + 1)}>Повторить сравнение</button></div>}
    {preview && <>
      <p>{preview.state === "current" ? "Сохранена текущая версия правил." : preview.state === "unclassified" ? "Выберите подкатегорию, чтобы получить её правила." : preview.state === "unknown" ? "Исходная версия неизвестна. Она не заменяется автоматически." : "Доступна новая версия правил. Сохранённые обязательства не изменятся."}</p>
      {preview.current && <p className="hint">Версия профиля: {preview.previous?.profile_version ?? "неизвестна"} → {preview.current.profile_version}</p>}
      {!!preview.changes.length && <ul>{preview.changes.map((change, index) => <li key={index}><strong>{change.label}: {change.kind === "added" ? "добавлено" : change.kind === "removed" ? "удалено" : "изменено"}</strong><div>Было: <RuleValue value={change.before} fields={preview.previous?.fields} /></div><div>Будет: <RuleValue value={change.after} fields={preview.current?.fields} /></div></li>)}</ul>}
      {preview.current && preview.state !== "current" && (draft ? <button type="button" className="btn btn-primary" disabled={loading || saving} onClick={() => void adopt()}>{saving ? "Сохраняем…" : "Изменения просмотрены — принять правила"}</button> : <p className="hint">Принять правила можно в черновике. Для потребности создайте повтор, для товара сначала снимите публикацию.</p>)}
    </>}
  </details>;
}

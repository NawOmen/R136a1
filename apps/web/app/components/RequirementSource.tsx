"use client";
import { russianMessage } from "../lib/russianMessages";
import { useState } from "react";
import { agents, EvidenceItem } from "../lib/agents";
import { displayValue } from "../lib/presentation";
import { getToken } from "../lib/api";

export default function RequirementSource({ runId, source, onInvalidate }: {
  runId: string; source: EvidenceItem; onInvalidate?: () => void;
}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const saved = source.source_id === "request_text" || source.source_id.startsWith("file_");
  async function open(original: boolean) {
    const token = getToken(); if (!token) return;
    setBusy(true); setError("");
    try {
      const value = await agents.source(token, runId, source.source_id, original);
      if (typeof value === "string") setText(value);
      else {
        const url = URL.createObjectURL(value); const anchor = document.createElement("a");
        anchor.href = url; anchor.download = source.source_name; anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (reason) { setError(reason instanceof Error ? russianMessage(reason.message) : "Не удалось открыть источник"); }
    finally { setBusy(false); }
  }
  const start = source.locator?.start, end = source.locator?.end;
  const located = text !== null && start !== undefined && end !== undefined && start >= 0 && end > start && end <= text.length;
  return <div className="hint">
    <p>{source.source_name} · {source.active === false ? "Источник удалён; подтверждение устарело" : `Уверенность извлечения ${Math.round(source.confidence * 100)}%`}
      {source.locator?.page && ` · страница ${source.locator.page}`}
      {source.locator?.seconds && ` · ${source.locator.seconds.join("–")} с`}
      {source.excerpt && ` · ${source.excerpt}`}</p>
    {source.normalization === "model_city_name" && <p>Модель нормализовала название города: {displayValue(source.value)}. Проверьте его по исходной записи в цитате.</p>}
    {saved && source.active !== false && <div className="actions">
      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void open(false)}>Открыть фрагмент и текст</button>
      <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void open(true)}>Скачать оригинал</button>
      {onInvalidate && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={onInvalidate}>Удалить источник</button>}
    </div>}
    {error && <p role="alert">{error}</p>}
    {text !== null && <details open><summary>Распознанный текст{source.locator?.located === false ? ": точный фрагмент не найден" : ""}</summary><pre style={{ whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto" }}>{located ? <>{text!.slice(0, start)}<mark>{text!.slice(start, end)}</mark>{text!.slice(end)}</> : text}</pre></details>}
  </div>;
}

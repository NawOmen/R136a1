"use client";

// Мои потребности (GET /needs/mine): статус, объём, бюджет, срок,
// переход к деталям. Повтор — новый черновик с новыми датами:
// старые файлы, допуски, резервы и согласия не переносятся.

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import {
  ApiError,
  formatRub,
  formatUnits,
  marketplace,
  Need,
  NEED_STATUS_LABELS,
  RepeatPreview,
} from "../lib/marketplace";
import { useMe } from "../lib/useMe";

function defaultDeadline(): string {
  const deadline = new Date();
  deadline.setDate(deadline.getDate() + 30);
  return deadline.toISOString().slice(0, 10);
}

export default function MyNeedsPage() {
  useMe(); // проверка входа и данных аккаунта
  const [query, setQuery] = useState("");
  const [needs, setNeeds] = useState<Need[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [repeatId, setRepeatId] = useState<string | null>(null);
  const [preview, setPreview] = useState<RepeatPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deadline, setDeadline] = useState(defaultDeadline());
  const [validUntil, setValidUntil] = useState(defaultDeadline());
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewRetry, setPreviewRetry] = useState(0);
  const previewGeneration = useRef(0);
  const [repeating, setRepeating] = useState(false);

  async function load() {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setNeeds(await marketplace.getMyNeeds(token));
    } catch (err: unknown) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить потребности.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setQuery(new URLSearchParams(window.location.search).get("q") ?? "");
    void load();
  }, []);

  useEffect(() => {
    const generation = ++previewGeneration.current;
    setPreview(null); setPreviewError(null);
    if (!repeatId) { setPreviewLoading(false); return; }
    const token = getToken();
    if (!token) return;
    setPreviewLoading(true);
    marketplace.previewRepeat(token, repeatId, deadline, validUntil).then((result) => {
      if (previewGeneration.current === generation) setPreview(result);
    }).catch((err: unknown) => {
      if (previewGeneration.current === generation) setPreviewError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось сравнить условия повтора.");
    }).finally(() => {
      if (previewGeneration.current === generation) setPreviewLoading(false);
    });
    return () => { previewGeneration.current += 1; };
  }, [repeatId, deadline, validUntil, previewRetry]);

  function openRepeat(need: Need) {
    previewGeneration.current += 1;
    setRepeatId(need.id); setPreview(null); setPreviewError(null); setPreviewLoading(true);
    setDeadline(defaultDeadline()); setValidUntil(defaultDeadline());
  }

  function changeDates(value: string, validity = false) {
    previewGeneration.current += 1; setPreview(null); setPreviewLoading(true);
    if (validity) setValidUntil(value); else setDeadline(value);
  }

  async function repeat(need: Need) {
    const token = getToken();
    if (!token) return;
    if (!preview || previewLoading || repeating) return;
    if (!deadline) {
      setError("Укажите новый срок выполнения.");
      return;
    }
    setRepeating(true);
    setError(null);
    try {
      const storageKey = `porukam:repeat:${need.id}:${deadline}:${validUntil || ""}`;
      const requestKey = sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
      sessionStorage.setItem(storageKey, requestKey);
      const copy = await marketplace.repeatNeed(token, need.id, deadline, requestKey, validUntil || undefined);
      sessionStorage.removeItem(storageKey);
      setNeeds((current) => [copy, ...current]);
      setRepeatId(null);
      setPreview(null);
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось повторить потребность.");
    } finally {
      setRepeating(false);
    }
  }

  const normalizedQuery = query.trim().toLocaleLowerCase("ru");
  const visibleNeeds = needs.filter(need => `${need.category} ${need.subcategory ?? ""} ${NEED_STATUS_LABELS[need.status]}`.toLocaleLowerCase("ru").includes(normalizedQuery));

  if (loading) return <p className="hint">Загрузка...</p>;

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Мои потребности</h1>
        <Link href="/needs/new" className="btn btn-primary btn-sm">
          Создать потребность
        </Link>
      </div>
      <p className="subtitle">Потребности, созданные вашими компаниями</p>
      <label className="catalog-search"><input aria-label="Поиск моих потребностей" placeholder="Категория или статус потребности" value={query} onChange={event => setQuery(event.target.value)} /></label>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}{" "}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void load()}>
            Повторить загрузку
          </button>
        </div>
      )}

      {!loading && !error && needs.length === 0 ? (
        <p className="hint">
          Потребностей пока нет. Создайте первую — производители смогут предложить свои условия.
        </p>
      ) : (
        <ul className="company-list">
          {visibleNeeds.length === 0 && needs.length > 0 && <li className="hint">По этому запросу потребности не найдены. Измените поиск.</li>}
          {visibleNeeds.map((need) => (
            <li key={need.id} className="company-item repeat-order">
              <Link href={`/needs/${need.id}`} className="company-item">
                <span className="company-item__name">
                  {need.category} · {formatUnits(need.volume_units)}
                </span>
                <span className="company-meta">
                  Бюджет: {formatRub(need.budget_rub)} · Срок: {need.deadline_date}
                </span>
                <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
              </Link>
              {repeatId === need.id ? (
                <div className="repeat-confirm">
                  <strong>Повтор закупки — новый черновик</strong>
                  {previewError && <div className="alert alert-error" role="alert">{previewError} <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPreviewRetry((value) => value + 1)}>Повторить сравнение</button></div>}
                  {previewLoading ? (
                    <p className="hint">Сравниваем прошлые и текущие условия...</p>
                  ) : preview ? (
                    <>
                      <ul className="company-list">
                        {preview.changes.map((change) => (
                          <li key={change.field} className="company-meta">
                            {change.field}: было — {change.was ?? "—"}; станет — {change.now ?? "—"}
                          </li>
                        ))}
                      </ul>
                      <p className="hint">
                        Не переносится: {preview.not_carried.join("; ")}. Потребуется новое
                        подтверждение и публикация.
                      </p>
                      {preview.warnings.map((warning) => (
                        <p key={warning} className="alert alert-warning">
                          {warning}
                        </p>
                      ))}
                    </>
                  ) : null}
                  <div className="field">
                    <label htmlFor={`deadline-${need.id}`}>Новый срок выполнения</label>
                    <input
                      id={`deadline-${need.id}`}
                      type="date"
                      value={deadline}
                      disabled={repeating}
                      onChange={(event) => changeDates(event.target.value)}
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`valid-${need.id}`}>Карточка актуальна до</label>
                    <input
                      id={`valid-${need.id}`}
                      type="date"
                      value={validUntil}
                      disabled={repeating}
                      onChange={(event) => changeDates(event.target.value, true)}
                    />
                  </div>
                  <div className="actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={repeating || previewLoading || !preview || !!previewError}
                      onClick={() => void repeat(need)}
                    >
                      {repeating ? "Создаём..." : "Да, создать черновик"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={repeating}
                      onClick={() => {
                        setRepeatId(null);
                        setPreview(null);
                      }}
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={repeating}
                  onClick={() => openRepeat(need)}
                >
                  Повторить заказ
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

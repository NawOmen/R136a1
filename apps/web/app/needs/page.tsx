"use client";
import { DateInput } from "../components/DateInput";
import { formatDate } from "../lib/dates";

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
import { NeedEditDialog } from "../components/NeedEditDialog";

type NeedSort = "recent" | "deadline" | "budget" | "status";

// Отменённые, истёкшие и закрытые сделки не редактируются и не удаляются повторно.
const CLOSED_STATUSES: Need["status"][] = ["cancelled", "expired", "matched"];

const SORT_LABELS: Record<NeedSort, string> = {
  recent: "Сначала новые",
  deadline: "Ближайший срок поставки",
  budget: "Самый большой бюджет",
  status: "По статусу",
};

const money = (value: Need["budget_rub"]) => (value === null || value === undefined ? -1 : Number(value));

function sortNeeds(items: Need[], sort: NeedSort): Need[] {
  const date = (value: string) => new Date(`${value}T00:00:00Z`).getTime();
  if (sort === "recent") return items;
  return [...items].sort((left, right) => {
    if (sort === "deadline") return date(left.deadline_date) - date(right.deadline_date);
    if (sort === "budget") return money(right.budget_rub) - money(left.budget_rub);
    const byStatus = NEED_STATUS_LABELS[left.status].localeCompare(NEED_STATUS_LABELS[right.status], "ru");
    return byStatus !== 0 ? byStatus : date(left.deadline_date) - date(right.deadline_date);
  });
}

function canEdit(need: Need): boolean {
  return !CLOSED_STATUSES.includes(need.status);
}

function canDelete(need: Need): boolean {
  // Потребность со сделкой не удаляется из списка: обязательство уже создано.
  return !CLOSED_STATUSES.includes(need.status);
}

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
  const [sort, setSort] = useState<NeedSort>("recent");
  const [statusFilter, setStatusFilter] = useState<"active" | "all">("active");
  const [editTarget, setEditTarget] = useState<Need | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [publicationBusy, setPublicationBusy] = useState<string | null>(null);

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

  const visibleNeeds = needs.filter(need => `${need.category} ${need.subcategory ?? ""} ${NEED_STATUS_LABELS[need.status]}`.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")))
    .filter(need => statusFilter === "all" || !CLOSED_STATUSES.includes(need.status));
  const orderedNeeds = sortNeeds(visibleNeeds, sort);
  const closedCount = needs.filter(need => CLOSED_STATUSES.includes(need.status)).length;

  async function removeNeed(need: Need) {
    const token = getToken();
    if (!token || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      const updated = await marketplace.cancelNeed(token, need.id);
      setNeeds(current => current.map(item => item.id === need.id ? { ...item, ...updated } : item));
      setDeleteId(null);
    } catch (err: unknown) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось удалить потребность.");
    } finally {
      setDeleting(false);
    }
  }

  async function togglePublication(need: Need) {
    const token = getToken();
    if (!token || publicationBusy) return;
    const hide = need.visibility === "open_anonymized";
    setPublicationBusy(need.id);
    setError(null);
    try {
      const payload = {
        company_id: need.company_id,
        category: need.category,
        subcategory: need.subcategory ?? null,
        characteristics: need.characteristics,
        volume_units: need.volume_units,
        budget_rub: need.budget_rub ?? null,
        deadline_date: need.deadline_date,
        delivery_address_id: need.delivery_address_id,
        visibility: hide ? ("closed" as const) : ("open_anonymized" as const),
        valid_until: need.valid_until ?? undefined,
        expected_revision: need.revision,
      };
      // Скрытие меняет версию потребности: сначала смотрим последствия,
      // затем сохраняем с их подтверждением.
      const impact = await marketplace.previewNeedEdit(token, need.id, payload);
      if (!impact.editable && Object.keys(impact.changes).length > 0) {
        setError("По этой потребности уже есть обязательства: скрыть её нельзя.");
        return;
      }
      const updated = await marketplace.editNeed(token, need.id, {
        ...payload,
        impact_hash: impact.requires_confirmation ? impact.impact_hash : undefined,
      });
      setNeeds(current => current.map(item => item.id === updated.id ? { ...item, ...updated } : item));
    } catch (err: unknown) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось изменить публикацию потребности.");
    } finally {
      setPublicationBusy(null);
    }
  }

  function applyEdit(updated: Need) {
    setNeeds(current => current.map(item => item.id === updated.id ? { ...item, ...updated } : item));
  }

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

      <div className="needs-toolbar">
        <div className="field"><label htmlFor="needs-sort">Сортировка</label><select id="needs-sort" value={sort} onChange={event => setSort(event.target.value as NeedSort)}>{(Object.keys(SORT_LABELS) as NeedSort[]).map(value => <option key={value} value={value}>{SORT_LABELS[value]}</option>)}</select></div>
        <div className="field"><label htmlFor="needs-scope">Показывать</label><select id="needs-scope" value={statusFilter} onChange={event => setStatusFilter(event.target.value as "active" | "all")}><option value="active">Только действующие</option><option value="all">Все, включая закрытые{closedCount > 0 ? ` (${closedCount})` : ""}</option></select></div>
        <p className="hint" role="status">Показано {orderedNeeds.length} из {needs.length}</p>
      </div>

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
          {visibleNeeds.length === 0 && needs.length > 0 && <li className="hint">По вашему запросу потребностей нет. Измените запрос в поиске наверху.</li>}
          {orderedNeeds.map((need) => (
            <li key={need.id} className="company-item repeat-order">
              <Link href={`/needs/${need.id}`} className="company-item">
                <span className="company-item__name">
                  {need.category} · {formatUnits(need.volume_units)}
                </span>
                <span className="company-meta">
                  Бюджет: {formatRub(need.budget_rub)} · Срок: {formatDate(need.deadline_date)}
                </span>
                <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
                {need.visibility !== "open_anonymized" && <span className="badge badge-hidden">Скрыта из публикации</span>}
              </Link>
              <div className="need-row-actions">
                {canEdit(need) && <button type="button" className="btn btn-secondary btn-sm" disabled={publicationBusy === need.id} onClick={() => void togglePublication(need)}>{publicationBusy === need.id ? "Сохраняем…" : need.visibility === "open_anonymized" ? "Скрыть из публикации" : "Вернуть в публикацию"}</button>}
                {canEdit(need) && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditTarget(need)}>Изменить</button>}
                {canDelete(need) && <button type="button" className="btn btn-secondary btn-sm" disabled={deleting} onClick={() => setDeleteId(deleteId === need.id ? null : need.id)}>Удалить</button>}
                {repeatId !== need.id && <button type="button" className="btn btn-secondary btn-sm" disabled={repeating} onClick={() => openRepeat(need)}>Повторить заказ</button>}
              </div>
              {repeatId === need.id && (
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
                    <DateInput
                      id={`deadline-${need.id}`}
                      value={deadline}
                      disabled={repeating}
                      onValueChange={(event) => changeDates(event)}
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`valid-${need.id}`}>Карточка актуальна до</label>
                    <DateInput
                      id={`valid-${need.id}`}
                      value={validUntil}
                      disabled={repeating}
                      onValueChange={(event) => changeDates(event, true)}
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
              )}
              {deleteId === need.id && (
                <div className="repeat-confirm">
                  <strong>Удалить потребность?</strong>
                  <p className="hint">Потребность будет отменена и уйдёт из подбора производителей. История и отклики сохранятся в архиве.</p>
                  <div className="actions">
                    <button type="button" className="btn btn-danger btn-sm" disabled={deleting} onClick={() => void removeNeed(need)}>{deleting ? "Удаляем…" : "Да, удалить"}</button>
                    <button type="button" className="btn btn-secondary btn-sm" disabled={deleting} onClick={() => setDeleteId(null)}>Отмена</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {editTarget && <NeedEditDialog key={editTarget.id} need={editTarget} onSaved={applyEdit} onClose={() => setEditTarget(null)} />}
    </div>
  );
}

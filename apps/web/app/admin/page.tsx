"use client";
import { formatDateTime } from "../lib/dates";

import { russianMessage } from "../lib/russianMessages";
import { russianLabel } from "../lib/presentation";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  Company,
  getToken,
  User,
  VerificationStatus,
  VerificationEvent,
  VERIFICATION_STATUS_LABELS,
} from "../lib/api";
import { CONFIRMABLE_ATTRIBUTES, DOCUMENT_TYPES, marketplace, PendingDocument, SupportTicket } from "../lib/marketplace";

export default function AdminPage() {
  const router = useRouter();
  const refreshVersion = useRef(0);
  const actionPending = useRef(false);
  const [agreements, setAgreements] = useState<Record<string, {document:string;version:string;accepted_at:string}[]>>({});
  const [notice, setNotice] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [statusFilter, setStatusFilter] = useState<VerificationStatus>("pending_review");
  const [search, setSearch] = useState("");
  const [history, setHistory] = useState<Record<string, VerificationEvent[]>>({});
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [response, setResponse] = useState<Record<string, string>>({});
  const [users, setUsers] = useState<User[]>([]);
  const [editorReasons, setEditorReasons] = useState<Record<string,string>>({});
  const [security, setSecurity] = useState<{event: string; created_at: string; correlation_id: string; actor_id?: string; target_id?: string; reason?: string}[]>([]);
  const [securityError, setSecurityError] = useState(false);
  const [securityAlert, setSecurityAlert] = useState(false);
  const [pendingDocuments, setPendingDocuments] = useState<PendingDocument[]>([]);
  const [docBusyId, setDocBusyId] = useState<string | null>(null);
  const [docScope, setDocScope] = useState<
    Record<string, { category: string; subcategory: string; note: string; confirms: Record<string, string> }>
  >({});

  useEffect(() => {
    if (!user?.is_marketplace_admin) return;
    let active = true;
    const refresh = async () => {
      const token = getToken();
      if (!token) return;
      try {
        const [events, alerts] = await Promise.all([api.getSecurityEvents(token), api.getSecurityEvents(token, true)]);
        if (active) {
          setSecurity(events); setSecurityError(false);
          setSecurityAlert(alerts.some(item => Date.now() - Date.parse(item.created_at) < 900000));
        }
      } catch { if (active) setSecurityError(true); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [user?.is_marketplace_admin]);

  const refreshPending = useCallback(async (token: string, selectedStatus: VerificationStatus = "pending_review", query = "") => {
    const version = ++refreshVersion.current;
    const results = await Promise.allSettled([
      api.getAdminCompanies(token, selectedStatus, query.trim().length >= 2 ? query.trim() : undefined),
      marketplace.getAdminSupportTickets(token), api.getAdminUsers(token), marketplace.getPendingDocuments(token),
    ]);
    if (version !== refreshVersion.current) return;
    const [companyResult, support, userResult, documents] = results;
    if (companyResult.status === "fulfilled") setCompanies(companyResult.value.companies);
    if (support.status === "fulfilled") setTickets(support.value);
    if (userResult.status === "fulfilled") setUsers(userResult.value.users);
    if (documents.status === "fulfilled") setPendingDocuments(documents.value);
    const failures = results.flatMap((result, index) => result.status === "rejected" ? [["компании", "обращения", "пользователи", "документы"][index]] : []);
    setError(failures.length ? `Не удалось обновить: ${failures.join(", ")}. Показаны ранее загруженные данные. Повторите загрузку.` : null);
  }, []);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    try {
      const me = await api.me(token);
      setUser(me.user);
      if (me.user.is_marketplace_admin) {
        await refreshPending(token, statusFilter, search);
      }
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить данные.");
    } finally {
      setLoading(false);
    }
  }, [refreshPending, router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function performAction(id: string, work: () => Promise<void>, message: string) {
    if (actionPending.current) return;
    actionPending.current = true; setBusyId(id); setActionError(null); setNotice("");
    try { await work(); setNotice(message); }
    catch (err) { setActionError(err instanceof Error ? russianMessage(err.message) : "Не удалось выполнить действие. Попробуйте ещё раз."); }
    finally { actionPending.current = false; setBusyId(null); }
  }
  async function ticketDecision(ticket: SupportTicket, status: "in_progress" | "resolved") {
    const token = getToken(); if (!token) return;
    const answer = (response[ticket.id] ?? ticket.admin_response ?? "").trim();
    if (status === "resolved" && !answer) { setActionError("Напишите ответ пользователю перед закрытием обращения."); return; }
    await performAction(ticket.id, async () => {
      await marketplace.updateAdminSupportTicket(token, ticket.id, {status, admin_response: answer || undefined});
      await refreshPending(token, statusFilter, search);
    }, status === "resolved" ? "Ответ сохранён. Обращение решено." : "Обращение взято в работу.");
  }
  async function toggleBlocked(item: User) {
    const token = getToken(); if (!token) return;
    if (!window.confirm(item.account_status === "blocked" ? "Разблокировать вход пользователя?" : "Заблокировать вход пользователя и завершить его сеансы?")) return;
    await performAction(item.id, async () => {
      await api.setUserBlocked(token, item.id, item.account_status !== "blocked");
      await refreshPending(token, statusFilter, search);
    }, item.account_status === "blocked" ? "Вход пользователя разблокирован." : "Вход пользователя заблокирован.");
  }
  async function downloadDocument(document: PendingDocument) {
    const token = getToken(); if (!token) return;
    await performAction(document.id, async () => {
      const blob = await marketplace.downloadEditorDocument(token, document.id);
      const url = URL.createObjectURL(blob); const link = window.document.createElement("a");
      link.href = url; link.download = document.name; link.click(); URL.revokeObjectURL(url);
    }, "Документ скачан для проверки.");
  }
  async function showHistory(company: Company) {
    const token = getToken(); if (!token) return;
    await performAction(company.id, async () => { const items = await api.getCompanyVerificationHistory(token, company.id); setHistory(current => ({...current, [company.id]: items})); }, "История проверки загружена.");
  }
  async function handleApprove(company: Company) {
    const token = getToken();
    if (!token) return;
    const comment = window.prompt("Причина подтверждения компании (обязательно):", "");
    if (comment === null) return;
    if (!comment.trim()) { setActionError("Укажите причину подтверждения компании."); return; }
    await performAction(company.id, async () => {
      await api.decideCompanyVerification(token, company.id, "approve", comment.trim());
      await refreshPending(token, statusFilter, search);
    }, "Компания подтверждена.");
  }

  function handleStartReject(company: Company) {
    setRejectingId(company.id);
    setReason("");
    setActionError(null);
  }

  async function handleConfirmReject(company: Company) {
    const token = getToken();
    if (!token) return;
    await performAction(company.id, async () => {
      await api.decideCompanyVerification(token, company.id, "reject", reason.trim() || undefined);
      setRejectingId(null);
      await refreshPending(token, statusFilter, search);
    }, "Компания отклонена. Причина сохранена.");
  }

  async function changeEditorRole(item: User) {
    const token = getToken(); if (!token) return;
    await performAction(item.id, async () => {
      const updated = await api.appointCategoryEditor(token, item.id, !item.is_category_editor, editorReasons[item.id]);
      setUsers(previous => previous.map(value => value.id === updated.id ? updated : value));
    }, item.is_category_editor ? "Роль редактора снята." : "Роль редактора назначена.");
  }

  function documentDecision(document: PendingDocument) {
    return docScope[document.id] ?? {
      category: document.scope_category ?? "",
      subcategory: document.scope_subcategory ?? "",
      note: "",
      confirms: {},
    };
  }

  function updateDocumentDecision(
    document: PendingDocument,
    patch: Partial<{ category: string; subcategory: string; note: string; confirms: Record<string, string> }>,
  ) {
    setDocScope((current) => ({ ...current, [document.id]: { ...documentDecision(document), ...patch } }));
  }

  function updateConfirms(document: PendingDocument, attribute: string, value: string) {
    const current = documentDecision(document).confirms;
    updateDocumentDecision(document, { confirms: { ...current, [attribute]: value } });
  }

  function parseConfirms(document: PendingDocument): Record<string, string[]> {
    const raw = documentDecision(document).confirms;
    const result: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(raw)) {
      const items = value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      if (items.length > 0) result[key] = items;
    }
    return result;
  }

  async function handleDocumentDecision(document: PendingDocument, decision: "verified" | "rejected") {
    const token = getToken();
    if (!token) return;
    const value = documentDecision(document);
    if (decision === "verified" && !value.category.trim()) {
      setActionError("Укажите область действия документа: без неё подтверждение невозможно.");
      return;
    }
    if (!value.note.trim()) {
      setActionError("Укажите причину решения по документу.");
      return;
    }
    await performAction(document.id, async () => {
      setDocBusyId(document.id);
      try {
        await marketplace.verifyDocument(token, document.id, {
          decision,
          scope_category: value.category.trim() || null,
          scope_subcategory: value.subcategory.trim() || null,
          confirms: decision === "verified" ? parseConfirms(document) : null,
          note: value.note.trim(),
        });
        await refreshPending(token, statusFilter, search);
      } finally { setDocBusyId(null); }
    }, decision === "verified" ? "Документ подтверждён." : "Документ отклонён. Причина сохранена.");
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (!user) {
    return (
      <div>
        <h1 className="page-title">Панель администратора</h1>
        <div className="alert alert-error">{error ?? "Не удалось загрузить данные."}</div>
        <Link href="/dashboard" className="btn btn-secondary">
          В личный кабинет
        </Link>
      </div>
    );
  }

  if (!user.is_marketplace_admin) {
    return (
      <div>
        <h1 className="page-title">Панель администратора</h1>
        <div className="alert alert-error">Нет доступа</div>
        <Link href="/dashboard" className="btn btn-secondary">
          В личный кабинет
        </Link>
      </div>
    );
  }

  return (
    <div>
      <section className="card" aria-live="polite">
        <h2>События безопасности</h2>
        {securityError && <p role="alert">Журнал недоступен. Проверьте работу сервиса авторизации.</p>}
        {securityAlert &&
          <p className="alert alert-error" role="alert">Обнаружено превышение лимита входа за последние 15 минут. Проверьте журнал.</p>}
        <p className="hint">Обновление каждые 30 секунд. Полный журнал хранится на сервере 30 дней.</p>
        {security.slice(0, 10).map(item => <p key={item.correlation_id + item.event}>
          {formatDateTime(item.created_at)} — {{
            "auth.rate_limited": "Превышен лимит попыток",
            "auth.login_failed": "Неудачный вход",
            "auth.login_success": "Успешный вход",
            "auth.blocked_login": "Вход заблокированного пользователя",
            "admin.account_status": "Изменён статус пользователя",
            "admin.category_editor_role": "Изменены полномочия редактора",
            "auth.password_changed": "Пароль изменён пользователем",
            "auth.password_reset": "Доступ восстановлен по почте",
            "auth.sessions_ended": "Сеансы завершены пользователем",
            "auth.recovery_delivery_failed": "Не удалось отправить письмо восстановления",
            "auth.recovery_requested": "Запрошено восстановление доступа",
            "auth.recovery_sent": "Отправлено письмо восстановления",
            "auth.logout": "Завершены все сеансы",
            "admin.first_operator": "Назначен первый администратор",
          }[item.event] ?? "Событие безопасности"}
          {(item.target_id || item.actor_id) && ` · ${users.find(user => user.id === (item.target_id || item.actor_id))?.email ?? "Аккаунт " + (item.target_id || item.actor_id)?.slice(0,8)}`}
          {item.reason && ` · ${item.reason}`}
        </p>)}
      </section>
      <div className="company-row">
        <h1 className="page-title">Панель администратора</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          В личный кабинет
        </Link>
      </div>
      <p className="subtitle">Очередь и история проверки компаний ({companies.length})</p>

      <div className="card form-grid">
        <div className="field"><label htmlFor="admin-status">Статус</label><select id="admin-status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as VerificationStatus)}>{Object.entries(VERIFICATION_STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        <div className="field"><label htmlFor="admin-search">Название или ИНН</label><input id="admin-search" type="text" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
        <button type="button" className="btn btn-secondary" onClick={() => { if(search.trim().length === 1){setError("Для поиска введите не менее двух символов.");return;} const token = getToken(); if (token) void refreshPending(token, statusFilter, search); }}>Применить фильтр</button>
      </div>

      {error && <div className="alert alert-error" role="alert">{error}<button type="button" className="btn btn-secondary" onClick={() => {const token=getToken(); if(token) void refreshPending(token,statusFilter,search);}}>Повторить загрузку</button></div>}{notice && <p className="alert alert-success" role="status">{notice}</p>}
      {actionError && <div className="alert alert-error">{actionError}</div>}

      {companies.length === 0 ? (
        <p className="hint">Нет компаний по выбранному фильтру.</p>
      ) : (
        <ul className="company-list">
          {companies.map((company) => (
            <li key={company.id} className="card">
              <div className="company-row">
                <div>
                  <div className="company-item__name">{company.display_name}</div>
                  <div className="company-meta">{company.full_name}</div>
                  <div className="company-meta">
                    {company.legal_form} · ИНН {company.inn} · {company.legal_address}
                  </div>
                </div>
                <span className={`badge badge-${company.verification_status}`}>
                  {VERIFICATION_STATUS_LABELS[company.verification_status]}
                </span>
              </div>
              <div className="actions">
                <button type="button" className="btn btn-secondary btn-sm" disabled={busyId !== null} onClick={() => void showHistory(company)}>История проверки</button>
                {company.verification_status === "pending_review" && <button
                  type="button"
                  className="btn btn-success btn-sm"
                  disabled={busyId === company.id}
                  onClick={() => void handleApprove(company)}
                >
                  {busyId === company.id ? "Сохраняем…" : "Подтвердить компанию"}
                </button>}
                {company.verification_status === "pending_review" && (rejectingId !== company.id ? (
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    disabled={busyId === company.id}
                    onClick={() => handleStartReject(company)}
                  >
                    Отклонить
                  </button>
                ) : (
                  <div className="reject-box">
                    <input
                      type="text"
                      placeholder="Причина отклонения"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      disabled={busyId === company.id}
                      onClick={() => void handleConfirmReject(company)}
                    >
                      {busyId === company.id ? "..." : "Подтвердить отклонение"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={busyId === company.id}
                      onClick={() => setRejectingId(null)}
                    >
                      Отмена
                    </button>
                  </div>
                ))}
              </div>
              {history[company.id] && <ul className="company-list">{history[company.id].map((event) => <li key={event.id}><span className="company-meta">{formatDateTime(event.created_at)}: {VERIFICATION_STATUS_LABELS[event.from_status]} → {VERIFICATION_STATUS_LABELS[event.to_status]}{event.reason ? ` · ${event.reason}` : ""}</span></li>)}</ul>}
            </li>
          ))}
        </ul>
      )}

      <section className="card" style={{ marginTop: 24 }}>
        <h2>Документы на проверке ({pendingDocuments.length})</h2>
        <p className="hint">
          Решение принимает администратор площадки. Документ без области действия не считается
          доказательством допуска, поэтому подтверждение требует указать категорию.
        </p>
        {pendingDocuments.length === 0 ? <p className="hint">Новых документов нет.</p> : (
          <ul className="company-list">
            {pendingDocuments.map((document) => {
              const value = documentDecision(document);
              const typeLabel = DOCUMENT_TYPES.find((item) => item.value === document.document_type)?.label ?? document.document_type;
              return (
                <li className="card" key={document.id}>
                  <div className="company-row">
                    <div>
                      <div className="company-item__name">{document.name}</div>
                      <div className="company-meta">{document.company_display_name ?? "Компания"} · {typeLabel}</div>
                    </div>
                  </div>
                  <div className="actions"><button type="button" className="btn btn-secondary btn-sm" disabled={busyId !== null} onClick={() => void downloadDocument(document)}>Скачать документ</button><Link href="/editor" className="btn btn-secondary btn-sm">Все характеристики и срок действия</Link></div>
                  <div className="form-grid">
                    <div className="field">
                      <label htmlFor={`doc-category-${document.id}`}>Область действия: категория<span className="req">*</span></label>
                      <input
                        id={`doc-category-${document.id}`}
                        type="text"
                        value={value.category}
                        onChange={(event) => updateDocumentDecision(document, { category: event.target.value })}
                        placeholder="Например, Упаковка и тара"
                      />
                    </div>
                    <div className="field">
                      <label htmlFor={`doc-subcategory-${document.id}`}>Подкатегория</label>
                      <input
                        id={`doc-subcategory-${document.id}`}
                        type="text"
                        value={value.subcategory}
                        onChange={(event) => updateDocumentDecision(document, { subcategory: event.target.value })}
                        placeholder="Например, Коробки"
                      />
                    </div>
                    {CONFIRMABLE_ATTRIBUTES.map((attribute) => (
                      <div className="field" key={attribute.value}>
                        <label htmlFor={`doc-confirm-${attribute.value}-${document.id}`}>
                          {attribute.label}<span className="opt">значения через запятую</span>
                        </label>
                        <input
                          id={`doc-confirm-${attribute.value}-${document.id}`}
                          type="text"
                          value={value.confirms[attribute.value] ?? ""}
                          onChange={(event) => updateConfirms(document, attribute.value, event.target.value)}
                          placeholder={attribute.value === "coating" ? "Например, PE" : "Например, крафт-картон"}
                        />
                      </div>
                    ))}
                    <div className="field">
                      <label htmlFor={`doc-note-${document.id}`}>Комментарий или причина отклонения</label>
                      <input
                        id={`doc-note-${document.id}`}
                        type="text"
                        value={value.note}
                        onChange={(event) => updateDocumentDecision(document, { note: event.target.value })}
                      />
                    </div>
                    <div className="actions">
                      <button
                        type="button"
                        className="btn btn-success btn-sm"
                        disabled={docBusyId === document.id}
                        onClick={() => void handleDocumentDecision(document, "verified")}
                      >
                        {docBusyId === document.id ? "..." : "Подтвердить применимость"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        disabled={docBusyId === document.id}
                        onClick={() => void handleDocumentDecision(document, "rejected")}
                      >
                        Отклонить
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="card" style={{ marginTop: 24 }}><h2>Пользователи ({users.length})</h2><div className="admin-user-grid">{users.map((item) => <div className="company-row" key={item.id}><div><b>{item.last_name} {item.first_name}</b><p className="hint mode-hint">{item.email} · {item.is_marketplace_admin ? "Администратор" : item.is_category_editor ? "Редактор категорий" : "Пользователь"}</p></div>{!item.is_marketplace_admin && <div><label>Основание назначения или снятия роли редактора<input maxLength={500} value={editorReasons[item.id] ?? ""} onChange={event=>setEditorReasons(previous=>({...previous,[item.id]:event.target.value}))} /></label><button type="button" className="btn btn-secondary btn-sm" disabled={busyId !== null || (editorReasons[item.id] ?? "").trim().length<3} onClick={() => void changeEditorRole(item)}>{item.is_category_editor ? "Снять роль редактора" : "Назначить редактором"}</button></div>}{!item.is_marketplace_admin && <button className="btn btn-secondary btn-sm" disabled={busyId !== null} onClick={() => void toggleBlocked(item)}>{item.account_status === "blocked" ? "Разблокировать" : "Заблокировать"}</button>}<button type="button" className="btn btn-secondary btn-sm" disabled={busyId !== null} onClick={() => {const token=getToken(); if(token) void performAction(item.id, async () => {const records = await api.getUserAgreements(token,item.id); setAgreements(current => ({...current, [item.id]: records}));}, "Подтверждения пользователя загружены.");}}>Принятые правила</button>{agreements[item.id] && <p>{agreements[item.id].length ? agreements[item.id].map(row => `${row.document === "rules" ? "Правила работы" : "Условия обработки данных"}: ${formatDateTime(row.accepted_at)} (${row.version})`).join("; ") : "Подтверждения не сохранены."}</p>}</div>)}</div></section>

      <h2 id="tickets" style={{ marginTop: 32 }}>Обращения пользователей ({tickets.length})</h2>
      {tickets.length === 0 ? <p className="hint">Обращений нет.</p> : <ul className="company-list">{tickets.map((ticket) => <li className="card" key={ticket.id}><div className="company-row"><strong>{ticket.subject}</strong><span className="badge">{russianLabel(ticket.status, "Статус уточняется")}</span></div><p>{ticket.message}</p><div className="field"><label htmlFor={`response-${ticket.id}`}>Ответ</label><textarea id={`response-${ticket.id}`} value={response[ticket.id] ?? ticket.admin_response ?? ""} onChange={(event) => setResponse((current) => ({ ...current, [ticket.id]: event.target.value }))} /></div><div className="actions"><button className="btn btn-secondary btn-sm" disabled={busyId !== null || ticket.status === "in_progress" || ticket.status === "resolved"} onClick={() => void ticketDecision(ticket, "in_progress")}>Взять в работу</button><button className="btn btn-success btn-sm" disabled={busyId !== null || ticket.status === "resolved"} onClick={() => void ticketDecision(ticket, "resolved")}>Отправить ответ и закрыть</button></div></li>)}</ul>}
    </div>
  );
}

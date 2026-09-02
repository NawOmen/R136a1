"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
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
import { marketplace, SupportTicket } from "../lib/marketplace";

export default function AdminPage() {
  const router = useRouter();
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

  const refreshPending = useCallback(async (token: string, selectedStatus: VerificationStatus = "pending_review", query = "") => {
    const result = await api.getAdminCompanies(token, selectedStatus, query || undefined);
    setCompanies(result.companies);
    const support = await marketplace.getAdminSupportTickets(token);
    setTickets(support);
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
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить данные.");
    } finally {
      setLoading(false);
    }
  }, [refreshPending, router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleApprove(company: Company) {
    const token = getToken();
    if (!token) return;
    setBusyId(company.id);
    setActionError(null);
    try {
      await api.decideCompanyVerification(token, company.id, "approve");
      await refreshPending(token, statusFilter, search);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Не удалось подтвердить компанию.");
    } finally {
      setBusyId(null);
    }
  }

  function handleStartReject(company: Company) {
    setRejectingId(company.id);
    setReason("");
    setActionError(null);
  }

  async function handleConfirmReject(company: Company) {
    const token = getToken();
    if (!token) return;
    setBusyId(company.id);
    setActionError(null);
    try {
      await api.decideCompanyVerification(token, company.id, "reject", reason.trim() || undefined);
      setRejectingId(null);
      await refreshPending(token, statusFilter, search);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Не удалось отклонить компанию.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (!user) {
    return (
      <div>
        <h1 className="page-title">Панель администратора</h1>
        <div className="alert alert-error">{error ?? "Не удалось загрузить данные."}</div>
        <Link href="/dashboard" className="btn btn-secondary">
          На главную
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
          На главную
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Панель администратора</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Очередь и история проверки компаний ({companies.length})</p>

      <div className="card form-grid">
        <div className="field"><label htmlFor="admin-status">Статус</label><select id="admin-status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as VerificationStatus)}>{Object.entries(VERIFICATION_STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        <div className="field"><label htmlFor="admin-search">Название или ИНН</label><input id="admin-search" type="text" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
        <button type="button" className="btn btn-secondary" onClick={() => { const token = getToken(); if (token) void refreshPending(token, statusFilter, search); }}>Применить фильтр</button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {actionError && <div className="alert alert-error">{actionError}</div>}

      {companies.length === 0 ? (
        <p className="hint">Нет компаний со статусом «На проверке».</p>
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
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => { const token = getToken(); if (!token) return; void api.getCompanyVerificationHistory(token, company.id).then((items) => setHistory((current) => ({ ...current, [company.id]: items }))); }}>История</button>
                {company.verification_status === "pending_review" && <button
                  type="button"
                  className="btn btn-success btn-sm"
                  disabled={busyId === company.id}
                  onClick={() => void handleApprove(company)}
                >
                  {busyId === company.id ? "..." : "Подтвердить"}
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
              {history[company.id] && <ul className="company-list">{history[company.id].map((event) => <li key={event.id}><span className="company-meta">{new Date(event.created_at).toLocaleString("ru-RU")}: {VERIFICATION_STATUS_LABELS[event.from_status]} → {VERIFICATION_STATUS_LABELS[event.to_status]}{event.reason ? ` · ${event.reason}` : ""}</span></li>)}</ul>}
            </li>
          ))}
        </ul>
      )}

      <h2 style={{ marginTop: 32 }}>Обращения поддержки ({tickets.length})</h2>
      {tickets.length === 0 ? <p className="hint">Обращений нет.</p> : <ul className="company-list">{tickets.map((ticket) => <li className="card" key={ticket.id}><div className="company-row"><strong>{ticket.subject}</strong><span className="badge">{ticket.status}</span></div><p>{ticket.message}</p><div className="field"><label htmlFor={`response-${ticket.id}`}>Ответ</label><textarea id={`response-${ticket.id}`} value={response[ticket.id] ?? ticket.admin_response ?? ""} onChange={(event) => setResponse((current) => ({ ...current, [ticket.id]: event.target.value }))} /></div><div className="actions"><button className="btn btn-secondary btn-sm" onClick={() => { const token = getToken(); if (!token) return; void marketplace.updateAdminSupportTicket(token, ticket.id, { status: "in_progress", admin_response: response[ticket.id] }).then(() => refreshPending(token, statusFilter, search)); }}>В работу</button><button className="btn btn-success btn-sm" onClick={() => { const token = getToken(); if (!token) return; void marketplace.updateAdminSupportTicket(token, ticket.id, { status: "resolved", admin_response: response[ticket.id] }).then(() => refreshPending(token, statusFilter, search)); }}>Ответить и решить</button></div></li>)}</ul>}
    </div>
  );
}

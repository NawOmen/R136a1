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
  VERIFICATION_STATUS_LABELS,
} from "../lib/api";

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

  const refreshPending = useCallback(async (token: string) => {
    const result = await api.getPendingCompanies(token);
    setCompanies(result.companies);
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
        await refreshPending(token);
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
      await refreshPending(token);
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
      await refreshPending(token);
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
      <p className="subtitle">Компании, ожидающие проверки ({companies.length})</p>

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
                <button
                  type="button"
                  className="btn btn-success btn-sm"
                  disabled={busyId === company.id}
                  onClick={() => void handleApprove(company)}
                >
                  {busyId === company.id ? "..." : "Подтвердить"}
                </button>
                {rejectingId !== company.id ? (
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
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

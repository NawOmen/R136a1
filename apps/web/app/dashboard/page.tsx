"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ACCOUNT_STATUS_LABELS,
  api,
  ApiError,
  clearToken,
  Company,
  getToken,
  User,
  VERIFICATION_STATUS_LABELS,
} from "../lib/api";

type Mode = "buy" | "sell" | null;

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    api
      .me(token)
      .then((result) => {
        setUser(result.user);
        setCompanies(result.companies);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Не удалось загрузить данные аккаунта.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function handleLogout() {
    clearToken();
    router.push("/login");
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (error) {
    return (
      <div>
        <div className="alert alert-error">{error}</div>
        <button type="button" className="btn btn-secondary" onClick={() => router.push("/login")}>
          На страницу входа
        </button>
      </div>
    );
  }

  if (!user) return null;

  const fullName = [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(" ");
  const canBuy = companies.some((company) => company.membership?.can_buy);
  const canSell = companies.some((company) => company.membership?.can_sell);

  return (
    <div>
      <div className="dashboard-head">
        <div>
          <h1 className="page-title">Личный кабинет</h1>
          <p className="subtitle">
            {fullName} · {user.email} · Статус: {ACCOUNT_STATUS_LABELS[user.account_status]}
          </p>
        </div>
        <div className="actions">
          {user.is_marketplace_admin && (
            <Link href="/admin" className="btn btn-secondary">
              Панель администратора
            </Link>
          )}
          <button type="button" className="btn btn-secondary" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </div>

      <section className="card">
        <h2>Режим работы</h2>
        <div className="mode-toggle" role="group" aria-label="Режим работы">
          <button
            type="button"
            className={mode === "buy" ? "active" : ""}
            disabled={!canBuy}
            title={canBuy ? undefined : "Нет компании с правом покупки"}
            onClick={() => setMode("buy")}
          >
            Покупаю
          </button>
          <button
            type="button"
            className={mode === "sell" ? "active" : ""}
            disabled={!canSell}
            title={canSell ? undefined : "Нет компании с правом продажи"}
            onClick={() => setMode("sell")}
          >
            Продаю
          </button>
        </div>
        {mode && (
          <p className="hint mode-hint">
            {mode === "buy"
              ? "Интерфейс покупки появится на этапе 3."
              : "Интерфейс продажи появится на этапе 3."}
          </p>
        )}
      </section>

      <section className="card">
        <div className="company-row">
          <h2>Мои компании</h2>
          <Link href="/company/new" className="btn btn-primary btn-sm">
            Создать компанию
          </Link>
        </div>
        {companies.length === 0 ? (
          <p className="hint mode-hint">Создайте компанию, чтобы начать работу на маркетплейсе.</p>
        ) : (
          <ul className="company-list">
            {companies.map((company) => (
              <li key={company.id}>
                <Link href={`/company/${company.id}`} className="company-item">
                  <span className="company-item__name">{company.display_name}</span>
                  <span className="company-meta">
                    {company.legal_form} · ИНН {company.inn}
                  </span>
                  <span className={`badge badge-${company.verification_status}`}>
                    {VERIFICATION_STATUS_LABELS[company.verification_status]}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

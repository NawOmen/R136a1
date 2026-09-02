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
import { marketplace } from "../lib/marketplace";

type Mode = "buy" | "sell" | null;

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(null);
  const [unreadCount, setUnreadCount] = useState(0);

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
        marketplace
          .getNotifications(token)
          .then((list) => setUnreadCount(list.filter((item) => !item.is_read).length))
          .catch(() => {
            // счётчик уведомлений не критичен для дашборда
          });
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
          <Link href="/support" className="btn btn-secondary">
            Поддержка
          </Link>
          <Link href="/kpi" className="btn btn-secondary">
            KPI и доверие
          </Link>
          <Link href="/notifications" className="btn btn-secondary">
            Уведомления{unreadCount > 0 ? ` (${unreadCount})` : ""}
          </Link>
          <Link href="/deals" className="btn btn-secondary">Сделки и сообщения</Link>
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
        {mode === "buy" && (
          <ul className="company-list">
            <li>
              <Link href="/catalog" className="company-item">
                <span className="company-item__name">Каталог товаров</span>
                <span className="company-meta">Публичный каталог производителей</span>
              </Link>
            </li>
            <li>
              <Link href="/needs/new" className="company-item">
                <span className="company-item__name">Создать потребность</span>
                <span className="company-meta">Опишите, что нужно купить</span>
              </Link>
            </li>
            <li>
              <Link href="/needs" className="company-item">
                <span className="company-item__name">Мои потребности</span>
                <span className="company-meta">Статусы и предложения по вашим закупкам</span>
              </Link>
            </li>
            <li>
              <Link href="/coalitions" className="company-item">
                <span className="company-item__name">Объединённые партии</span>
                <span className="company-meta">Отдельно подтвердите условия вашей компании</span>
              </Link>
            </li>
            <li>
              <Link href="/resilience" className="company-item">
                <span className="company-item__name">Устойчивость сделок</span>
                <span className="company-meta">Резервы, сценарии N-1/N-2 и безопасная симуляция</span>
              </Link>
            </li>
          </ul>
        )}

        {mode === "sell" && (
          <ul className="company-list">
            <li>
              <Link href="/seller/profile" className="company-item">
                <span className="company-item__name">Производственный профиль</span>
                <span className="company-meta">Адрес площадки и информация о производстве</span>
              </Link>
            </li>
            <li>
              <Link href="/seller/products" className="company-item">
                <span className="company-item__name">Мои товары</span>
                <span className="company-meta">Каталог и публикация товаров</span>
              </Link>
            </li>
            <li><Link href="/seller/analytics" className="company-item"><span className="company-item__name">Продажи и статистика</span><span className="company-meta">Сделки, оборот и загрузка мощности</span></Link></li>
            <li>
              <Link href="/seller/capacity" className="company-item">
                <span className="company-item__name">Мощности</span>
                <span className="company-meta">Доступные объёмы по дням</span>
              </Link>
            </li>
            <li>
              <Link href="/seller/documents" className="company-item">
                <span className="company-item__name">Документы</span>
                <span className="company-meta">Сертификаты и декларации</span>
              </Link>
            </li>
            <li>
              <Link href="/seller/passport" className="company-item">
                <span className="company-item__name">Паспорт возможностей</span>
                <span className="company-meta">Технологии, оборудование, материалы</span>
              </Link>
            </li>
            <li>
              <Link href="/seller/requests" className="company-item">
                <span className="company-item__name">Подходящие запросы</span>
                <span className="company-meta">Открытые потребности покупателей</span>
              </Link>
            </li>
            <li>
              <Link href="/seller/opportunities" className="company-item">
                <span className="company-item__name">Что сейчас нужно рынку</span>
                <span className="company-meta">Объяснимые возможности из подтверждённого спроса</span>
              </Link>
            </li>
            <li>
              <Link href="/coalitions" className="company-item">
                <span className="company-item__name">Групповые предложения</span>
                <span className="company-meta">Черновики, подтверждения и общие партии</span>
              </Link>
            </li>
            <li>
              <Link href="/seller/reserves" className="company-item">
                <span className="company-item__name">Резерв и сбои</span>
                <span className="company-meta">Подтверждение мощности и сообщение об отказе</span>
              </Link>
            </li>
          </ul>
        )}

        {mode === null && (
          <p className="hint mode-hint">Выберите режим, чтобы открыть разделы маркетплейса.</p>
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

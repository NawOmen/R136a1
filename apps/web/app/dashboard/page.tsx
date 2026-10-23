"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ACCOUNT_STATUS_LABELS,
  api,
  ApiError,
  clearToken,
  Company,
  getToken, WORKSPACE_CHANGED_EVENT,
  User,
  VERIFICATION_STATUS_LABELS,
} from "../lib/api";
import { marketplace } from "../lib/marketplace";
import { OnboardingTour } from "../components/OnboardingTour";
import { BuyerSavingsPanel } from "../components/BuyerSavingsPanel";

type Mode = "buy" | "sell" | null;

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [mode, setMode] = useState<Mode>(null);
  const [companyId, setCompanyId] = useState("");
  const [nextError, setNextError] = useState(false);
  const [stepRetry, setStepRetry] = useState(0);
  const [nextStep, setNextStep] = useState<{ title: string; description: string; href: string } | null>(null);

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
        const savedCompany = window.localStorage.getItem(`porukam:dashboard-company:${result.user.id}`);
        const selected = result.companies.find((item) => item.id === savedCompany) ?? result.companies[0];
        setCompanyId(selected?.id ?? "");
        const savedMode = window.localStorage.getItem(`porukam:work-mode:${result.user.id}:${selected?.id}`);
        setMode(savedMode === "sell" && selected?.membership?.can_sell ? "sell" : selected?.membership?.can_buy ? "buy" : selected?.membership?.can_sell ? "sell" : null);


      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить данные аккаунта.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function handleLogout() {
    if (loggingOut || !window.confirm("Выйти из аккаунта на всех устройствах?")) return;
    const token = getToken();
    setLoggingOut(true); setLogoutError("");
    try {
      if (token) await api.logout(token);
      clearToken();
      window.localStorage.removeItem("porukam-work-mode");
      router.replace("/login");
      router.refresh();
    } catch (err) {
      setLogoutError(err instanceof Error ? russianMessage(err.message) : "Не удалось завершить сеансы. Повторите выход.");
    } finally { setLoggingOut(false); }
  }

  function selectMode(next: Exclude<Mode, null>) {
    setMode(next);
    if (user) window.localStorage.setItem(`porukam:work-mode:${user.id}:${companyId}`, next);
    window.dispatchEvent(new Event(WORKSPACE_CHANGED_EVENT));
  }

  const selectedCompany = companies.find((item) => item.id === companyId);
  const canBuy = !!selectedCompany?.membership?.can_buy;
  const canSell = !!selectedCompany?.membership?.can_sell;

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    setNextStep(null); setNextError(false);
    marketplace.getNextStep(getToken()!, user.is_marketplace_admin ? undefined : companyId || undefined, mode)
      .then((result) => { if (!cancelled) setNextStep(result); }).catch(() => { if (!cancelled) setNextError(true); });
    return () => { cancelled = true; };
  }, [user, companyId, mode, stepRetry]);

  // При смене компаний сбрасываем чужой режим: нельзя оставаться в режиме без прав.
  useEffect(() => {
    if (!user || user.is_marketplace_admin) return;
    if (mode === "buy" && !canBuy) setMode(canSell ? "sell" : null);
    if (mode === "sell" && !canSell) setMode(canBuy ? "buy" : null);
  }, [companies, mode, canBuy, canSell, user]);

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

  if (user.is_marketplace_admin) {
    return <div><div className="dashboard-head"><div><h1 className="page-title">Рабочее место администратора</h1><p className="subtitle">Управление компаниями, пользователями и поддержкой</p></div><button type="button" className="btn btn-secondary" disabled={loggingOut} onClick={() => void handleLogout()}>{loggingOut ? "Выходим…" : "Выйти"}</button></div>{logoutError && <p className="alert alert-error" role="alert">{logoutError}</p>}<section className="journey-grid"><Link className="journey-card" href="/admin"><span>01</span><b>Заявки компаний</b><small>Проверка, причины решений и история</small></Link><Link className="journey-card" href="/admin#tickets"><span>02</span><b>Сообщения в поддержку</b><small>Очередь поддержки и ответы</small></Link><Link className="journey-card" href="/notifications"><span>03</span><b>Уведомления</b><small>Системные события администратора</small></Link></section></div>;
  }

  const fullName = [user.last_name, user.first_name, user.middle_name].filter(Boolean).join(" ");
  const buyerCompany = selectedCompany?.membership?.can_buy ? selectedCompany : undefined;


  return (
    <div className="dashboard-page">
      {logoutError && <p className="alert alert-error" role="alert">{logoutError}</p>}
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
            Показатели и доверие
          </Link>

          <Link href="/deals" className="btn btn-secondary">Сделки и сообщения</Link>
          {user.is_marketplace_admin && (
            <Link href="/admin" className="btn btn-secondary">
              Панель администратора
            </Link>
          )}
          <button type="button" className="btn btn-secondary" disabled={loggingOut} onClick={() => void handleLogout()}>
            {loggingOut ? "Выходим…" : "Выйти"}
          </button>
        </div>
      </div>

      {companies.length > 0 && <div className="field"><label htmlFor="dashboard-company">Рабочая компания</label><select id="dashboard-company" value={companyId} onChange={(event) => {
        setNextStep(null); setCompanyId(event.target.value);
        window.localStorage.setItem(`porukam:dashboard-company:${user.id}`, event.target.value);
        window.dispatchEvent(new Event(WORKSPACE_CHANGED_EVENT));
        const selected = companies.find((item) => item.id === event.target.value);
        const saved = window.localStorage.getItem(`porukam:work-mode:${user.id}:${event.target.value}`);
        setMode(saved === "sell" && selected?.membership?.can_sell ? "sell" : selected?.membership?.can_buy ? "buy" : selected?.membership?.can_sell ? "sell" : null);
      }}>{companies.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></div>}
      <section className="workspace-card">
        <div className="workspace-card__head"><div><h2>Рабочие разделы</h2><p>Один аккаунт может покупать и продавать от имени компании</p></div><div className="mode-toggle" role="group" aria-label="Режим работы">
          <button
            type="button"
            aria-pressed={mode === "buy"}
            className={mode === "buy" ? "active" : ""}
            disabled={!canBuy}
            title={canBuy ? undefined : "Нет компании с правом покупки"}
            onClick={() => selectMode("buy")}
          >
            Покупаю
          </button>
          <button
            type="button"
            aria-pressed={mode === "sell"}
            className={mode === "sell" ? "active" : ""}
            disabled={!canSell}
            title={canSell ? undefined : "Нет компании с правом продажи"}
            onClick={() => selectMode("sell")}
          >
            Продаю
          </button>
        </div></div>
        <p className="hint">Выберите компанию и режим. Ниже — ближайшее действие именно для них.</p>
      {nextStep && (
        <section className="card" aria-live="polite">
          <span className="eyebrow">Следующий шаг</span>
          <h2>{nextStep.title}</h2>
          <p className="subtitle">{nextStep.description}</p>
          <div className="actions">
            <Link href={nextStep.href} className="btn btn-primary btn-sm">
              Продолжить
            </Link>
          </div>
        </section>
      )}
        {nextError && <p role="alert">Не удалось определить следующий шаг. <button type="button" onClick={() => setStepRetry(value => value + 1)}>Повторить</button></p>}
        {!nextStep && !nextError && <p role="status">Подбираем следующий шаг…</p>}
        {mode && <div className="actions">
          <Link className="btn btn-secondary" href={mode === "buy" ? "/needs/new" : "/seller/requests"}>{mode === "buy" ? "Новый запрос с ИИ" : "Запросы покупателей"}</Link>
          <Link className="btn btn-secondary" href={mode === "buy" ? "/needs" : "/seller/products"}>{mode === "buy" ? "Мои запросы" : "Мои товары"}</Link>
        </div>}
        <details className="workflow-details"><summary>Все рабочие разделы</summary>
        {mode === "buy" && (
          <ul className="company-list">
            <li><Link href="/buyer/analytics" className="company-item"><span className="company-item__name">Закупки и статистика</span><span className="company-meta">Цены, приёмка, возвраты и отмены</span></Link></li>
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
            <li><Link href="/seller/analytics" className="company-item"><span className="company-item__name">Продажи и статистика</span><span className="company-meta">Заказы, приёмка, возвраты и прибыль</span></Link></li>
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
        </details>
      </section>

      {buyerCompany && <details className="workflow-details"><summary>Экономия на закупках</summary><BuyerSavingsPanel companyId={buyerCompany.id} /></details>}
      <OnboardingTour canBuy={canBuy} canSell={canSell} mode={mode} scope={`${user.id}:${companyId}:${mode}`} companyId={companyId || undefined} />

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

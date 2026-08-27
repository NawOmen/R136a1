"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  Company,
  getToken,
  LegalForm,
  UpdateCompanyInput,
  VERIFICATION_STATUS_LABELS,
} from "../../lib/api";

export default function CompanyPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const router = useRouter();

  const [company, setCompany] = useState<Company | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [submittingReview, setSubmittingReview] = useState(false);
  const [canBuy, setCanBuy] = useState(false);
  const [canSell, setCanSell] = useState(false);
  const [savingPermissions, setSavingPermissions] = useState(false);

  // Форма редактирования
  const [fullName, setFullName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [legalForm, setLegalForm] = useState<LegalForm>("ООО");
  const [inn, setInn] = useState("");
  const [ogrn, setOgrn] = useState("");
  const [ogrnip, setOgrnip] = useState("");
  const [kpp, setKpp] = useState("");
  const [legalAddress, setLegalAddress] = useState("");
  const initializedRef = useRef(false);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    try {
      const result = await api.me(token);
      const found = result.companies.find((item) => item.id === id) ?? null;
      if (!found) setNotFound(true);
      setCompany(found);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить компанию.");
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (company && !initializedRef.current) {
      setFullName(company.full_name);
      setDisplayName(company.display_name);
      setLegalForm(company.legal_form);
      setInn(company.inn);
      setOgrn(company.ogrn ?? "");
      setOgrnip(company.ogrnip ?? "");
      setKpp(company.kpp ?? "");
      setLegalAddress(company.legal_address);
      setCanBuy(company.membership?.can_buy ?? false);
      setCanSell(company.membership?.can_sell ?? false);
      initializedRef.current = true;
    }
  }, [company]);

  function buildUpdateInput(): UpdateCompanyInput {
    const input: UpdateCompanyInput = {
      full_name: fullName.trim(),
      display_name: displayName.trim(),
      legal_form: legalForm,
      inn: inn.trim(),
      legal_address: legalAddress.trim(),
      kpp: kpp.trim() || null,
    };
    if (legalForm === "ООО") {
      input.ogrn = ogrn.trim() || null;
    } else {
      input.ogrnip = ogrnip.trim() || null;
    }
    return input;
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateCompany(token, company.id, buildUpdateInput());
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить изменения.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSavePermissions() {
    const token = getToken();
    if (!token || !company) return;
    setSavingPermissions(true);
    setError(null);
    try {
      await api.updateMembership(token, company.id, { can_buy: canBuy, can_sell: canSell });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить режимы.");
    } finally {
      setSavingPermissions(false);
    }
  }

  async function handleSubmitReview() {
    const token = getToken();
    if (!token || !company) return;
    if (!window.confirm("Отправить компанию на проверку? После отправки редактирование будет недоступно.")) {
      return;
    }
    setSubmittingReview(true);
    setError(null);
    try {
      await api.submitCompanyForReview(token, company.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отправить компанию на проверку.");
    } finally {
      setSubmittingReview(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (notFound || !company) {
    return (
      <div>
        <h1 className="page-title">Компания не найдена</h1>
        <Link href="/dashboard" className="btn btn-secondary">
          На главную
        </Link>
      </div>
    );
  }

  const isAdmin = company.membership?.is_admin === true;
  const canEdit =
    isAdmin && (company.verification_status === "draft" || company.verification_status === "rejected");

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">{company.display_name}</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <section className="card">
        <div className="company-row">
          <h2>Карточка компании</h2>
          <span className={`badge badge-${company.verification_status}`}>
            {VERIFICATION_STATUS_LABELS[company.verification_status]}
          </span>
        </div>
        {company.verification_status === "rejected" && company.rejection_reason && (
          <p className="hint mode-hint">Причина отклонения: {company.rejection_reason}</p>
        )}
        <dl className="company-details">
          <div>
            <dt>Полное название</dt>
            <dd>{company.full_name}</dd>
          </div>
          <div>
            <dt>Форма</dt>
            <dd>{company.legal_form}</dd>
          </div>
          <div>
            <dt>ИНН</dt>
            <dd>{company.inn}</dd>
          </div>
          <div>
            <dt>{company.legal_form === "ООО" ? "ОГРН" : "ОГРНИП"}</dt>
            <dd>{company.legal_form === "ООО" ? company.ogrn ?? "—" : company.ogrnip ?? "—"}</dd>
          </div>
          <div>
            <dt>КПП</dt>
            <dd>{company.kpp ?? "—"}</dd>
          </div>
          <div>
            <dt>Страна</dt>
            <dd>{company.country}</dd>
          </div>
          <div>
            <dt>Юридический адрес</dt>
            <dd>{company.legal_address}</dd>
          </div>
          <div>
            <dt>Права</dt>
            <dd>
              {company.membership
                ? [
                    company.membership.can_buy ? "Покупка" : null,
                    company.membership.can_sell ? "Продажа" : null,
                  ]
                    .filter(Boolean)
                    .join(", ") || "—"
                : "—"}
            </dd>
          </div>
        </dl>
      </section>

      {isAdmin && (
        <section className="card">
          <h2>Режимы работы</h2>
          <p className="hint mode-hint">
            Один аккаунт может и покупать, и продавать — включите нужные режимы.
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={canBuy}
              onChange={(event) => setCanBuy(event.target.checked)}
              disabled={savingPermissions}
            />
            Покупаю
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={canSell}
              onChange={(event) => setCanSell(event.target.checked)}
              disabled={savingPermissions}
            />
            Продаю
          </label>
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={savingPermissions || (!canBuy && !canSell)}
              onClick={() => void handleSavePermissions()}
            >
              {savingPermissions ? "Сохраняем..." : "Сохранить режимы"}
            </button>
          </div>
        </section>
      )}

      {canEdit && (
        <section className="card">
          <h2>Редактирование</h2>
          <p className="hint mode-hint">
            Статус «{VERIFICATION_STATUS_LABELS[company.verification_status]}» — компанию можно
            редактировать и отправить на проверку.
          </p>
          <form onSubmit={handleSave}>
            <div className="field">
              <label htmlFor="full_name">Полное название</label>
              <input
                id="full_name"
                type="text"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="display_name">Отображаемое название</label>
              <input
                id="display_name"
                type="text"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="legal_form">Форма</label>
              <select
                id="legal_form"
                value={legalForm}
                onChange={(event) => setLegalForm(event.target.value as LegalForm)}
              >
                <option value="ООО">ООО</option>
                <option value="ИП">ИП</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="inn">ИНН</label>
              <input
                id="inn"
                type="text"
                value={inn}
                onChange={(event) => setInn(event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="ogrn">{legalForm === "ООО" ? "ОГРН" : "ОГРНИП"}</label>
              <input
                id="ogrn"
                type="text"
                value={legalForm === "ООО" ? ogrn : ogrnip}
                onChange={(event) =>
                  legalForm === "ООО" ? setOgrn(event.target.value) : setOgrnip(event.target.value)
                }
              />
            </div>
            <div className="field">
              <label htmlFor="kpp">КПП</label>
              <input
                id="kpp"
                type="text"
                value={kpp}
                onChange={(event) => setKpp(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="legal_address">Юридический адрес</label>
              <input
                id="legal_address"
                type="text"
                value={legalAddress}
                onChange={(event) => setLegalAddress(event.target.value)}
                required
              />
            </div>
            <div className="actions">
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? "Сохраняем..." : "Сохранить изменения"}
              </button>
              <button
                type="button"
                className="btn btn-success"
                disabled={submittingReview}
                onClick={() => void handleSubmitReview()}
              >
                {submittingReview ? "Отправляем..." : "Отправить на проверку"}
              </button>
            </div>
          </form>
        </section>
      )}
    </div>
  );
}

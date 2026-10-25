"use client";

import { russianMessage } from "../../lib/russianMessages";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, CreateCompanyInput, getToken, LegalForm } from "../../lib/api";

export default function NewCompanyPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [legalForm, setLegalForm] = useState<LegalForm>("ООО");
  const [inn, setInn] = useState("");
  const [ogrn, setOgrn] = useState("");
  const [ogrnip, setOgrnip] = useState("");
  const [kpp, setKpp] = useState("");
  const [legalAddress, setLegalAddress] = useState("");
  const [canBuy, setCanBuy] = useState(false);
  const [canSell, setCanSell] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token) return;

    setError(null);
    setSubmitting(true);
    try {
      const payload: CreateCompanyInput = {
        full_name: fullName.trim(),
        display_name: displayName.trim(),
        legal_form: legalForm,
        inn: inn.trim(),
        legal_address: legalAddress.trim(),
        can_buy: canBuy,
        can_sell: canSell,
      };
      if (legalForm === "ООО") {
        if (ogrn.trim()) payload.ogrn = ogrn.trim();
      } else if (ogrnip.trim()) {
        payload.ogrnip = ogrnip.trim();
      }
      if (kpp.trim()) payload.kpp = kpp.trim();

      await api.createCompany(token, payload);
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError ? russianMessage(err.message) : "Не удалось создать компанию. Попробуйте ещё раз.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <h1 className="page-title">Создание компании</h1>
      <p className="subtitle">Заполните реквизиты компании</p>

      {error && <div className="alert alert-error">{error}</div>}

      <form className="card" onSubmit={handleSubmit}>
        <p className="hint form-required-note">Обязательные поля отмечены <span className="req">*</span>.</p>
        <div className="field">
          <label htmlFor="full_name">Полное название<span className="req">*</span></label>
          <input
            id="full_name"
            type="text"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="display_name">Отображаемое название<span className="req">*</span></label>
          <input
            id="display_name"
            type="text"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="legal_form">Форма<span className="req">*</span></label>
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
          <label htmlFor="inn">ИНН<span className="req">*</span></label>
          <input
            id="inn"
            type="text"
            inputMode="numeric"
            pattern={legalForm === "ООО" ? "[0-9]{10}" : "[0-9]{12}"}
            maxLength={legalForm === "ООО" ? 10 : 12}
            aria-describedby="inn-hint"
            value={inn}
            onChange={(event) => setInn(event.target.value)}
            required
          />
          <p id="inn-hint" className="hint">{legalForm === "ООО" ? "10 цифр для ООО" : "12 цифр для ИП"}</p>
        </div>
        <div className="field">
          <label htmlFor="ogrn">
            {legalForm === "ООО" ? "ОГРН" : "ОГРНИП"}
            <span className="opt">необязательно</span>
          </label>
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
          <label htmlFor="kpp">КПП<span className="opt">необязательно</span></label>
          <input
            id="kpp"
            type="text"
            value={kpp}
            onChange={(event) => setKpp(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="legal_address">Юридический адрес<span className="req">*</span></label>
          <input
            id="legal_address"
            type="text"
            value={legalAddress}
            onChange={(event) => setLegalAddress(event.target.value)}
            required
          />
        </div>

        <fieldset className="company-mode-group" aria-describedby={!canBuy && !canSell ? "company-mode-hint" : undefined}>
          <legend className="visually-hidden">Режимы работы компании</legend>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={canBuy}
              onChange={(event) => setCanBuy(event.target.checked)}
            />
            Покупаю
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={canSell}
              onChange={(event) => setCanSell(event.target.checked)}
            />
            Продаю
          </label>
          {!canBuy && !canSell && (
            <p className="hint mode-hint" id="company-mode-hint">Выберите хотя бы один режим: «Покупаю» или «Продаю».</p>
          )}
        </fieldset>

        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting || (!canBuy && !canSell)}>
            {submitting ? "Создаём..." : "Создать компанию"}
          </button>
          <Link href="/dashboard" className="btn btn-secondary">
            Отмена
          </Link>
        </div>
      </form>
    </div>
  );
}

"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { AuthFrame, AuthSubmit } from "../components/auth/AuthFrame";
import { PasswordInput } from "../components/auth/PasswordInput";
import styles from "../components/auth/AuthFrame.module.css";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, getToken, RegisterInput, setToken } from "../lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [lastName, setLastName] = useState("");
  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rulesAccepted, setRulesAccepted] = useState(false);
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false);
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/dashboard");
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!rulesAccepted || !privacyAcknowledged) {setError("Подтвердите правила работы и ознакомление с условиями обработки данных."); return;}
    setSubmitting(true);
    try {
      const payload: RegisterInput = {
        rules_version: "rules-1", privacy_version: "privacy-1",
        rules_accepted: true, privacy_acknowledged: true,
        last_name: lastName.trim(),
        first_name: firstName.trim(),
        email: email.trim(),
        password,
      };
      if (middleName.trim()) payload.middle_name = middleName.trim();
      if (phone.trim()) payload.phone = phone.trim();

      const result = await api.register(payload);
      setToken(result.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError ? russianMessage(err.message) : "Не удалось зарегистрироваться. Попробуйте ещё раз.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthFrame registration>
      <h1 className="page-title">Регистрация</h1>
      <p className="subtitle">Один аккаунт для закупок и продаж.</p>
      <p className="hint" style={{ marginTop: -14, marginBottom: 16 }}>
        Обязательные поля отмечены <span className="req">*</span>.
      </p>

      {error && <div className="alert alert-error" role="alert">{error}</div>}

      <form className="card" onSubmit={handleSubmit}>
        <div className={styles.names}><div className="field">
          <label htmlFor="last_name">Фамилия<span className="req">*</span></label>
          <input
            id="last_name"
            type="text"
            value={lastName}
            onChange={(event) => setLastName(event.target.value)}
            required
            autoComplete="family-name"
          />
        </div>
        <div className="field">
          <label htmlFor="first_name">Имя<span className="req">*</span></label>
          <input
            id="first_name"
            type="text"
            value={firstName}
            onChange={(event) => setFirstName(event.target.value)}
            required
            autoComplete="given-name"
          />
        </div>
        </div>
        <div className={styles.names}>
<div className="field">
          <label htmlFor="middle_name">Отчество <span className="opt">необязательно</span></label>
          <input
            id="middle_name"
            type="text"
            value={middleName}
            onChange={(event) => setMiddleName(event.target.value)}
            autoComplete="additional-name"
          />
        </div>
        <div className="field">
          <label htmlFor="phone">Телефон <span className="opt">необязательно</span></label>
          <input
            id="phone"
            type="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoComplete="tel"
          />
        </div>
        </div>
        <div className="field">
          <label htmlFor="email">Электронная почта<span className="req">*</span></label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            autoComplete="email"
          />
        </div>
        <div className="field">
          <label htmlFor="password">Пароль<span className="req">*</span></label>
          <PasswordInput
            id="password"
            minLength={12}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete="new-password"
          />
          <p className="hint">Не менее 12 символов.</p>
        </div>
        <label className={styles.consent}><input type="checkbox" required checked={rulesAccepted} onChange={event => setRulesAccepted(event.target.checked)} /> Принимаю <Link href="/info/legal" target="_blank" rel="noopener">правила работы</Link></label>
        <label className={styles.consent}><input type="checkbox" required checked={privacyAcknowledged} onChange={event => setPrivacyAcknowledged(event.target.checked)} /> Ознакомлен с <Link href="/info/privacy" target="_blank" rel="noopener">условиями обработки данных</Link></label>
        <AuthSubmit submitting={submitting} text="Зарегистрироваться" pendingText="Создаём аккаунт…" />
      </form>

      <p className="hint">
        Уже есть аккаунт? <Link href="/login">Войти</Link>
      </p>
    </AuthFrame>
  );
}

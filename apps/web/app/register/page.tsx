"use client";

import Link from "next/link";
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
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/dashboard");
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const payload: RegisterInput = {
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
        err instanceof ApiError ? err.message : "Не удалось зарегистрироваться. Попробуйте ещё раз.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <h1 className="page-title">Регистрация</h1>
      <p className="subtitle">Создайте аккаунт, чтобы начать работу</p>

      {error && <div className="alert alert-error">{error}</div>}

      <form className="card" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="last_name">Фамилия</label>
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
          <label htmlFor="first_name">Имя</label>
          <input
            id="first_name"
            type="text"
            value={firstName}
            onChange={(event) => setFirstName(event.target.value)}
            required
            autoComplete="given-name"
          />
        </div>
        <div className="field">
          <label htmlFor="middle_name">Отчество</label>
          <input
            id="middle_name"
            type="text"
            value={middleName}
            onChange={(event) => setMiddleName(event.target.value)}
            autoComplete="additional-name"
          />
        </div>
        <div className="field">
          <label htmlFor="email">Email</label>
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
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete="new-password"
          />
        </div>
        <div className="field">
          <label htmlFor="phone">Телефон</label>
          <input
            id="phone"
            type="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            autoComplete="tel"
          />
        </div>
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Регистрируем..." : "Зарегистрироваться"}
          </button>
        </div>
      </form>

      <p className="hint">
        Уже есть аккаунт? <Link href="/login">Войти</Link>
      </p>
    </div>
  );
}

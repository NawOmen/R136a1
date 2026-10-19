"use client";

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, getToken, setToken } from "../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      const result = await api.login({ email: email.trim(), password });
      setToken(result.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось войти. Попробуйте ещё раз.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell"><aside className="auth-aside"><span className="eyebrow">ПоРукам для бизнеса</span><h2>Один аккаунт для закупок и продаж</h2><p>Товары, запросы и сделки вашей компании — в одном кабинете.</p></aside><div className="auth-page">
      <span className="eyebrow">С возвращением</span><h1 className="page-title">Войти в аккаунт</h1>
      <p className="subtitle">Продолжите закупки и продажи в ПоРукам</p>

      {error && <div className="alert alert-error">{error}</div>}

      <form className="card" onSubmit={handleSubmit}>
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
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            autoComplete="current-password"
          />
        </div>
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Входим..." : "Войти"}
          </button>
        </div>
      </form>

      <p className="hint">
        <Link href="/recover">Забыли пароль?</Link>
      </p>
      <p className="hint">
        Нет аккаунта? <Link href="/register">Зарегистрироваться</Link>
      </p>
    </div></div>
  );
}

"use client";

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
      setError(err instanceof ApiError ? err.message : "Не удалось войти. Попробуйте ещё раз.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <h1 className="page-title">Вход</h1>
      <p className="subtitle">Войдите в аккаунт, чтобы продолжить</p>

      {error && <div className="alert alert-error">{error}</div>}

      <form className="card" onSubmit={handleSubmit}>
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
        Нет аккаунта? <Link href="/register">Зарегистрироваться</Link>
      </p>
    </div>
  );
}

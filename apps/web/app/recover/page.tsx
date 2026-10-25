"use client";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { russianMessage } from "../lib/russianMessages";

export default function RecoveryPage() {
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const [email, setEmail] = useState(""); const [code, setCode] = useState(""); const [password, setPassword] = useState(""); const [repeat, setRepeat] = useState("");
  const [sent, setSent] = useState(false); const [done, setDone] = useState(false); const [busy, setBusy] = useState(false); const pending = useRef(false);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); if (pending.current) return;
    if (sent && password !== repeat) { setError("Новые пароли не совпадают."); return; }
    pending.current = true; setBusy(true); setError("");
    try {
      const result = sent ? await api.resetPassword(code.trim(), password) : await api.requestRecovery(email.trim());
      setNotice(result.message); if (sent) { setDone(true); setCode(""); setPassword(""); setRepeat(""); } else setSent(true);
    } catch (e) { setError(e instanceof Error ? russianMessage(e.message) : "Не удалось восстановить доступ. Попробуйте ещё раз."); }
    finally { pending.current = false; setBusy(false); }
  }
  return <div className="auth-page"><h1 className="page-title">Восстановить доступ</h1>
    {notice && <p className="alert alert-success" role="status">{notice}</p>}{error && <p className="alert alert-error" role="alert">{error}</p>}
    {!done && <form className="card" onSubmit={submit}><fieldset disabled={!ready || busy} style={{border:0, padding:0, minWidth:0}}>
      {!sent ? <div className="field"><label htmlFor="recovery-email">Почта аккаунта</label><input id="recovery-email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></div> : <>
        <div className="field"><label htmlFor="recovery-code">Код из письма</label><input id="recovery-code" required autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} /></div>
        <div className="field"><label htmlFor="recovery-password">Новый пароль</label><input id="recovery-password" type="password" minLength={12} maxLength={72} autoComplete="new-password" required value={password} onChange={e => setPassword(e.target.value)} /><p className="hint">Не менее 12 символов.</p></div>
        <div className="field"><label htmlFor="recovery-repeat">Повторите новый пароль</label><input id="recovery-repeat" type="password" autoComplete="new-password" required value={repeat} onChange={e => setRepeat(e.target.value)} /></div>
      </>}
      <button className="btn btn-primary">{busy ? "Подождите…" : sent ? "Сохранить новый пароль" : "Получить код на почту"}</button>
      {sent && <button type="button" className="btn btn-secondary" onClick={() => {setSent(false); setNotice(""); setError(""); setCode(""); setPassword(""); setRepeat("");}}>Запросить новое письмо</button>}
    </fieldset></form>}
    <p><Link href="/login">Вернуться ко входу</Link></p><p className="hint"><Link href="/info/contacts">Связаться с поддержкой</Link></p>
  </div>;
}

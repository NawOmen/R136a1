"use client";

import { FormEvent, useRef, useState } from "react";
import { api, getToken, setToken } from "../lib/api";
import { russianMessage } from "../lib/russianMessages";

export default function AccountAccess() {
  const [current, setCurrent] = useState(""); const [password, setPassword] = useState(""); const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false); const pending = useRef(false);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  async function save(event?: FormEvent) {
    event?.preventDefault(); if (pending.current) return;
    if (event && password !== repeat) { setError("Новые пароли не совпадают."); return; }
    const token = getToken(); if (!token) return;
    pending.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const result = event ? await api.changePassword(token, current, password) : await api.endOtherSessions(token);
      setToken(result.access_token); setCurrent(""); setPassword(""); setRepeat("");
      setNotice(event ? "Пароль изменён. Остальные сеансы завершены." : "Остальные сеансы завершены. Вы остались в аккаунте на этом устройстве.");
    } catch (e) { setError(e instanceof Error ? russianMessage(e.message) : "Не удалось изменить доступ. Попробуйте ещё раз."); }
    finally { pending.current = false; setBusy(false); }
  }
  return <section className="card"><h2>Пароль и доступ</h2>
    {error && <p className="alert alert-error" role="alert">{error}</p>}{notice && <p className="alert alert-success" role="status">{notice}</p>}
    <form onSubmit={save}><fieldset disabled={busy} style={{border: 0, padding: 0}}>
      <div className="field"><label htmlFor="current-password">Текущий пароль</label><input id="current-password" type="password" autoComplete="current-password" required value={current} onChange={e => setCurrent(e.target.value)} /></div>
      <div className="field"><label htmlFor="new-password">Новый пароль</label><input id="new-password" type="password" autoComplete="new-password" required minLength={12} maxLength={72} value={password} onChange={e => setPassword(e.target.value)} /><p className="hint">Не менее 12 символов. Используйте отдельный пароль для ПоРукам.</p></div>
      <div className="field"><label htmlFor="repeat-password">Повторите новый пароль</label><input id="repeat-password" type="password" autoComplete="new-password" required value={repeat} onChange={e => setRepeat(e.target.value)} /></div>
      <button className="btn btn-primary">{busy ? "Сохраняем…" : "Сменить пароль"}</button>
    </fieldset></form>
    <p className="hint">Если входили с чужого устройства, завершите остальные сеансы.</p>
    <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void save()}>Завершить остальные сеансы</button>
  </section>;
}

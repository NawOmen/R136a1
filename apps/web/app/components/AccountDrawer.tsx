"use client";

import Link from "next/link";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ActiveLink } from "./ActiveLink";
import { Icon } from "./Icon";
import { api, AUTH_CHANGED_EVENT, clearToken, getToken, User } from "../lib/api";

type Theme = "light" | "dark";

function readTheme(): Theme {
  try { return window.localStorage.getItem("porukam-theme") === "dark" ? "dark" : "light"; }
  catch { return "light"; }
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try { window.localStorage.setItem("porukam-theme", theme); } catch { /* Session-only theme when browser storage is unavailable. */ }
}

export function AccountDrawer() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) return;
    const drawer = drawerRef.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer?.querySelector<HTMLButtonElement>("button")?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
      if (event.key !== "Tab") return;
      const items = drawer?.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
      if (!items?.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", handleKey); if (previousFocus?.isConnected) previousFocus.focus(); };
  }, [open]);
  const [user, setUser] = useState<User | null>(null);
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    setOpen(false);
    let generation = 0;
    const sync = () => {
      const current = ++generation;
      const token = getToken();
      if (!token) { setUser(null); setOpen(false); return; }
      void api.me(token).then(result => { if (current === generation) setUser(result.user); }).catch(() => { if (current === generation) { setUser(null); setOpen(false); } });
    };
    const saved = readTheme();
    setTheme(saved); applyTheme(saved); sync();
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { generation++; window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [pathname]);
  function toggleTheme() { const next = theme === "light" ? "dark" : "light"; setTheme(next); applyTheme(next); }
  function logout() { clearToken(); window.localStorage.removeItem("porukam-work-mode"); setOpen(false); router.replace("/"); router.refresh(); }
  return <div className="account-control">
    <button className="icon-button theme-toggle" type="button" onClick={toggleTheme} aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"} title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}><Icon name={theme === "dark" ? "sun" : "moon"} size={19} /></button>
    {!user && <><Link className="account-login" href="/login">Войти</Link><Link className="btn btn-outline-primary btn-sm" href="/register">Регистрация</Link></>}
    {user && <button className="account-avatar" type="button" aria-label="Открыть личный кабинет" aria-expanded={open} aria-controls={open ? "account-drawer" : undefined} onClick={() => setOpen(true)}>{user.first_name.slice(0, 1)}{user.last_name.slice(0, 1)}</button>}
    {open && user && createPortal(<><button className="drawer-backdrop" tabIndex={-1} aria-label="Закрыть панель" onClick={() => setOpen(false)} /><aside ref={drawerRef} id="account-drawer" role="dialog" aria-modal="true" className="account-drawer" aria-label="Меню аккаунта">
      <div className="company-row"><div><h2>{user.first_name} {user.last_name}</h2><span className="hint">{user.email}</span></div><button className="drawer-close" aria-label="Закрыть" onClick={() => setOpen(false)}><Icon name="close" /></button></div>
      <nav onClick={(event) => { if ((event.target as HTMLElement).closest("a")) setOpen(false); }}><ActiveLink href={user.is_marketplace_admin ? "/admin" : "/dashboard"}>Личный кабинет</ActiveLink>{(user.is_category_editor || user.is_marketplace_admin) && <ActiveLink href="/editor">Кабинет редактора</ActiveLink>}{!user.is_marketplace_admin && <><ActiveLink href="/coalitions">Коалиции</ActiveLink><ActiveLink href="/deals">Сделки</ActiveLink></>}<ActiveLink href="/notifications">Уведомления</ActiveLink><ActiveLink href="/settings">Настройки</ActiveLink>{!user.is_marketplace_admin && <ActiveLink href="/support">Поддержка</ActiveLink>}<button type="button" className="toggle-motion" onClick={toggleTheme}>Тема: {theme === "dark" ? "тёмная" : "светлая"}</button><button className="drawer-logout" type="button" onClick={logout}>Выйти</button></nav>
    </aside></>, document.body)}
  </div>;
}

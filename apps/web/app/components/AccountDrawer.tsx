"use client";

import Link from "next/link";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ActiveLink } from "./ActiveLink";
import { api, AUTH_CHANGED_EVENT, clearToken, getToken, User } from "../lib/api";

import { applyTheme, savedTheme, THEME_CHANGED_EVENT, Theme } from "../lib/theme";

export function AccountDrawer() {
  const pathname = usePathname();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [open, setOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) return;
    const drawer = drawerRef.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    const background = Array.from(document.querySelectorAll<HTMLElement>(".site-header, #main-content, .site-footer"));
    const previousInert = background.map(element => element.inert);
    background.forEach(element => { element.inert = true; });
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
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
      background.forEach((element, index) => { element.inert = previousInert[index]; });
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);
  const [user, setUser] = useState<User | null>(null);
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    setOpen(false);
    const sync = () => {
      const token = getToken();
      if (!token) { setUser(null); return; }
      void api.me(token).then((result) => setUser(result.user)).catch(() => setUser(null));
    };
    const saved = savedTheme();
    setTheme(saved); document.documentElement.dataset.theme = saved; sync();
    const syncTheme = () => setTheme(savedTheme());
    window.addEventListener(THEME_CHANGED_EVENT, syncTheme);
    window.addEventListener("storage", syncTheme);
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener(THEME_CHANGED_EVENT, syncTheme); window.removeEventListener("storage", syncTheme); window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [pathname]);
  function toggleTheme() { const next = theme === "light" ? "dark" : "light"; setTheme(next); applyTheme(next); }
  async function logout() {
    if (signingOut || !window.confirm("Выйти из аккаунта на всех устройствах?")) return;
    const token = getToken(); setSigningOut(true); setLogoutError("");
    try {
      if (token) await api.logout(token);
      clearToken(); window.localStorage.removeItem("porukam-work-mode"); setOpen(false); router.replace("/"); router.refresh();
    } catch {setLogoutError("Не удалось завершить сеансы. Повторите выход.");}
    finally {setSigningOut(false);}
  }
  return <div className="account-control">
    <button className="theme-toggle" type="button" aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"} title={theme === "dark" ? "Светлая тема" : "Тёмная тема"} onClick={toggleTheme}>{theme === "dark" ? "☀" : "☾"}</button>
    {!user && <><Link className="account-login" href="/login">Войти</Link><Link className="btn btn-outline-primary btn-sm" href="/register">Регистрация</Link></>}
    {user && <button className="account-avatar" type="button" aria-label="Открыть личный кабинет" aria-expanded={open} aria-controls={open ? "account-drawer" : undefined} onClick={() => setOpen(true)}>{user.first_name.slice(0, 1)}{user.last_name.slice(0, 1)}</button>}
    {open && user && typeof document !== "undefined" && createPortal(<><button className="drawer-backdrop" tabIndex={-1} aria-label="Закрыть панель" onClick={() => setOpen(false)} /><aside ref={drawerRef} id="account-drawer" role="dialog" aria-modal="true" className="account-drawer" aria-label="Меню аккаунта">
      <div className="company-row"><div><h2>{user.first_name} {user.last_name}</h2><span className="hint">{user.email}</span></div><button className="drawer-close" aria-label="Закрыть" onClick={() => setOpen(false)}>×</button></div>
      {logoutError && <p role="alert">{logoutError}</p>}<nav onClick={(event) => { if ((event.target as HTMLElement).closest("a")) setOpen(false); }}><ActiveLink href={user.is_marketplace_admin ? "/admin" : "/dashboard"}>Личный кабинет</ActiveLink>{(user.is_category_editor || user.is_marketplace_admin) && <ActiveLink href="/editor">Кабинет редактора</ActiveLink>}<ActiveLink href="/notifications">Уведомления</ActiveLink><ActiveLink href="/settings">Настройки</ActiveLink>{!user.is_marketplace_admin && <ActiveLink href="/support">Поддержка</ActiveLink>}<button type="button" onClick={toggleTheme}>Тема: {theme === "dark" ? "тёмная" : "светлая"}</button><button className="drawer-logout" type="button" disabled={signingOut} onClick={() => void logout()}>{signingOut ? "Выходим…" : "Выйти"}</button></nav>
    </aside></>, document.body)}
  </div>;
}

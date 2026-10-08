"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ActiveLink } from "./ActiveLink";
import { api, AUTH_CHANGED_EVENT, clearToken, getToken, User } from "../lib/api";

type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem("porukam-theme", theme);
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
    return () => { document.removeEventListener("keydown", handleKey); if (previousFocus?.isConnected) previousFocus.focus(); };
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
    const saved = window.localStorage.getItem("porukam-theme") === "light" ? "light" : "dark";
    setTheme(saved); applyTheme(saved); sync();
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [pathname]);
  function toggleTheme() { const next = theme === "light" ? "dark" : "light"; setTheme(next); applyTheme(next); }
  function logout() { clearToken(); setOpen(false); router.replace("/"); router.refresh(); }
  return <div className="account-control">
    {!user && <><Link className="account-login" href="/login">Войти</Link><Link className="btn btn-outline-primary btn-sm" href="/register">Регистрация</Link></>}
    {user && <button className="account-avatar" type="button" aria-label="Открыть личный кабинет" aria-expanded={open} aria-controls={open ? "account-drawer" : undefined} onClick={() => setOpen(true)}>{user.first_name.slice(0, 1)}{user.last_name.slice(0, 1)}</button>}
    {open && user && <><button className="drawer-backdrop" tabIndex={-1} aria-label="Закрыть панель" onClick={() => setOpen(false)} /><aside ref={drawerRef} id="account-drawer" role="dialog" aria-modal="true" className="account-drawer" aria-label="Меню аккаунта">
      <div className="company-row"><div><h2>{user.first_name} {user.last_name}</h2><span className="hint">{user.email}</span></div><button className="drawer-close" aria-label="Закрыть" onClick={() => setOpen(false)}>×</button></div>
      <nav onClick={(event) => { if ((event.target as HTMLElement).closest("a")) setOpen(false); }}><ActiveLink href={user.is_marketplace_admin ? "/admin" : "/dashboard"}>Личный кабинет</ActiveLink>{(user.is_category_editor || user.is_marketplace_admin) && <ActiveLink href="/editor">Кабинет редактора</ActiveLink>}<ActiveLink href="/notifications">Уведомления</ActiveLink><ActiveLink href="/settings">Настройки</ActiveLink>{!user.is_marketplace_admin && <ActiveLink href="/support">Поддержка</ActiveLink>}<button type="button" onClick={toggleTheme}>Тема: {theme === "dark" ? "тёмная" : "светлая"}</button><button className="drawer-logout" type="button" onClick={logout}>Выйти</button></nav>
    </aside></>}
  </div>;
}

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
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
    {user && <button className="account-avatar" type="button" aria-label="Открыть личный кабинет" onClick={() => setOpen(true)}>{user.first_name.slice(0, 1)}{user.last_name.slice(0, 1)}</button>}
    {open && user && <><button className="drawer-backdrop" aria-label="Закрыть панель" onClick={() => setOpen(false)} /><aside className="account-drawer" aria-label="Меню аккаунта">
      <div className="company-row"><div><h2>{user.first_name} {user.last_name}</h2><span className="hint">{user.email}</span></div><button className="drawer-close" aria-label="Закрыть" onClick={() => setOpen(false)}>×</button></div>
      <nav><Link href={user.is_marketplace_admin ? "/admin" : "/dashboard"}>Личный кабинет</Link><Link href="/notifications">Уведомления</Link><Link href="/settings">Настройки</Link>{!user.is_marketplace_admin && <Link href="/support">Поддержка</Link>}<button type="button" onClick={toggleTheme}>Тема: {theme === "dark" ? "тёмная" : "светлая"}</button><button className="drawer-logout" type="button" onClick={logout}>Выйти</button></nav>
    </aside></>}
  </div>;
}

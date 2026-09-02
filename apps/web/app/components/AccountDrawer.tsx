"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";

export function AccountDrawer() {
  const [open, setOpen] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  useEffect(() => setAuthenticated(Boolean(getToken())), []);
  return <div className="account-control">
    {!authenticated && <><Link className="btn btn-secondary btn-sm" href="/login">Войти</Link><Link className="btn btn-primary btn-sm" href="/register">Зарегистрироваться</Link></>}
    {authenticated && <button className="btn btn-secondary btn-sm" type="button" onClick={() => setOpen(true)}>Личный кабинет</button>}
    {open && <><button className="drawer-backdrop" aria-label="Закрыть панель" onClick={() => setOpen(false)} /><aside className="account-drawer" aria-label="Личный кабинет">
      <div className="company-row"><h2>Личный кабинет</h2><button className="btn btn-secondary btn-sm" onClick={() => setOpen(false)}>Закрыть</button></div>
      <nav><Link href="/dashboard">Режимы работы</Link><Link href="/notifications">Уведомления</Link><Link href="/seller/products">Мои товары</Link><Link href="/seller/analytics">Продажи и статистика</Link><Link href="/settings">Настройки</Link><Link href="/support">Поддержка</Link></nav>
    </aside></>}
  </div>;
}

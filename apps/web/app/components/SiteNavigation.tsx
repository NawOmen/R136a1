"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, AUTH_CHANGED_EVENT, getToken } from "../lib/api";

export function SiteNavigation() {
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    const sync = () => { const token = getToken(); if (!token) return setAdmin(false); void api.me(token).then((result) => setAdmin(result.user.is_marketplace_admin)).catch(() => setAdmin(false)); };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, sync);
  }, []);
  return <nav className="site-nav" aria-label="Основная навигация"><Link href="/catalog">Каталог</Link><Link href="/ai-procurement">Закупки с ИИ</Link>{!admin && <Link href="/support">Поддержка</Link>}<Link href="/knowledge">Помощь</Link></nav>;
}

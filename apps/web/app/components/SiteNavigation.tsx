"use client";

import { ActiveLink } from "./ActiveLink";
import { FormEvent, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api, AUTH_CHANGED_EVENT, getToken } from "../lib/api";

export function SiteNavigation() {
  const pathname = usePathname();
  const [admin, setAdmin] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const sync = () => {
      const token = getToken();
      setAuthenticated(Boolean(token));
      if (!token) return setAdmin(false);
      void api.me(token).then((result) => setAdmin(result.user.is_marketplace_admin)).catch(() => setAdmin(false));
    };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, sync);
  }, []);

  const demandHref = authenticated ? "/seller/requests" : "/login";
  const demandActive = pathname.startsWith("/seller/requests") || pathname.startsWith("/needs");

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = query.trim();
    const target = demandActive ? demandHref : "/catalog";
    window.location.assign(value ? `${target}?q=${encodeURIComponent(value)}` : target);
  }

  return <div className="market-navigation">
    <nav className="market-lanes" aria-label="Раздел рынка">
      <ActiveLink href="/catalog">Товары</ActiveLink>
      {!admin && <ActiveLink paths={["/seller/requests", "/needs"]} href={demandHref}>Потребности</ActiveLink>}
    </nav>
    <form className="market-search" role="search" onSubmit={search}>
      <span aria-hidden="true">⌕</span>
      <input aria-label="Поиск по маркетплейсу" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={demandActive ? "Поиск потребностей" : "Поиск товаров и производителей"} />
      <button type="submit">Найти</button>
    </form>
    <nav className="site-nav" aria-label="Рабочие разделы">
      {authenticated && !admin && <ActiveLink href="/coalitions">Коалиции</ActiveLink>}
      {authenticated && !admin && <ActiveLink href="/deals">Сделки</ActiveLink>}
      <ActiveLink href="/ai-procurement">ИИ-закупки</ActiveLink>
      {!admin && <ActiveLink href="/support">Поддержка</ActiveLink>}
      <ActiveLink href="/knowledge">Помощь</ActiveLink>
    </nav>
  </div>;
}

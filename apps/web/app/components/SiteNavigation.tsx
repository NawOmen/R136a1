"use client";

import { ActiveLink } from "./ActiveLink";
import { FormEvent, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api, AUTH_CHANGED_EVENT, getToken, WORKSPACE_CHANGED_EVENT } from "../lib/api";

export function SiteNavigation() {
  const pathname = usePathname();
  const [admin, setAdmin] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [demandHref, setDemandHref] = useState("/login");
  const [query, setQuery] = useState("");
  useEffect(() => {
    let generation = 0;
    const sync = () => {
      const current = ++generation;
      const token = getToken();
      setAuthenticated(Boolean(token));
      if (!token) { setAdmin(false); setDemandHref("/login"); return; }
      void api.me(token).then((result) => {
        if (current !== generation) return;
        setAdmin(result.user.is_marketplace_admin);
        const companyId = window.localStorage.getItem(`porukam:dashboard-company:${result.user.id}`);
        const company = result.companies.find(item => item.id === companyId) ?? result.companies[0];
        const mode = window.localStorage.getItem(`porukam:work-mode:${result.user.id}:${company?.id}`);
        setDemandHref(company?.membership?.can_sell && (!company.membership.can_buy || mode === "sell") ? "/seller/requests" : "/needs");
      }).catch(() => { if (current === generation) { setAdmin(false); setDemandHref("/login"); } });
    };
    sync(); window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener(WORKSPACE_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { generation++; window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener(WORKSPACE_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [pathname]);

  const demandActive = pathname.startsWith("/seller/requests") || pathname.startsWith("/needs");

  useEffect(() => { setQuery(new URLSearchParams(window.location.search).get("q") ?? ""); }, [pathname]);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = query.trim();
    const target = demandActive ? (pathname.startsWith("/needs") ? "/needs" : "/seller/requests") : "/catalog";
    window.location.assign(value ? `${target}?q=${encodeURIComponent(value)}` : target);
  }

  return <div className="market-navigation">
    <nav className="market-lanes" aria-label="Раздел рынка">
      <ActiveLink href="/catalog">Товары</ActiveLink>
      {!admin && <ActiveLink paths={["/seller/requests", "/needs"]} href={demandHref}>Потребности</ActiveLink>}
    </nav>
    <form className="market-search" role="search" onSubmit={search}>
      <span aria-hidden="true">⌕</span>
      <input aria-label="Поиск по маркетплейсу" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={demandActive ? "Поиск потребностей" : "Поиск товаров и категорий"} />
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

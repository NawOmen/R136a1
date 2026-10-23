"use client";

import Link from "next/link";
import { ActiveLink } from "./ActiveLink";
import { useEffect, useId, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { api, AUTH_CHANGED_EVENT, getToken, WORKSPACE_CHANGED_EVENT } from "../lib/api";
import { Icon } from "./Icon";
import { LiquidSurface } from "./LiquidSurface";

export function SiteNavigation() {
  const pathname = usePathname();
  const [admin, setAdmin] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [demandHref, setDemandHref] = useState("/login");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const disclosure = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    let generation = 0;
    const sync = () => {
      const current = ++generation;
      const token = getToken();
      setAuthenticated(Boolean(token)); setAdmin(false); setDemandHref("/login");
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
  useEffect(() => { setOpen(false); setQuery(new URLSearchParams(window.location.search).get("q") ?? ""); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!disclosure.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  const demandActive = pathname.startsWith("/seller/requests") || pathname.startsWith("/needs");
  const workLinks = <>{authenticated && !admin && <><ActiveLink href="/coalitions">Коалиции</ActiveLink><ActiveLink href="/deals">Сделки</ActiveLink></>}<Link className="ai-nav-action" href="/needs/new"><Icon name="spark" size={18} />Закупить с ИИ</Link><ActiveLink href="/knowledge">Помощь</ActiveLink></>;
  return <div className="market-navigation">
    <nav className="market-lanes" aria-label="Раздел рынка"><ActiveLink paths={["/catalog"]} href="/catalog">Товары</ActiveLink>{!admin && <ActiveLink paths={["/seller/requests", "/needs"]} href={demandHref}>Потребности</ActiveLink>}</nav>
    <form className="market-search" role="search" action={demandActive ? (pathname.startsWith("/needs") ? "/needs" : "/seller/requests") : "/catalog"} method="get"><Icon name="search" size={21} /><input name="q" aria-label="Поиск по маркетплейсу" value={query} onChange={event => setQuery(event.target.value)} placeholder={demandActive ? "Найти потребность" : "Найти товар или категорию"} /><LiquidSurface as="div" variant="rail" className="liquid-action liquid-action--primary search-action"><button type="submit" aria-label="Найти">Найти<Icon name="arrow" size={17} /></button></LiquidSurface></form>
    <div className="market-sections">

      <nav className="site-nav" aria-label="Рабочие разделы"><Link className="ai-nav-action" href="/needs/new"><Icon name="spark" size={18} />ИИ-закупка</Link><ActiveLink href="/knowledge">Поддержка</ActiveLink></nav>
      {!admin && <Link className="header-request" href="/needs/new">Разместить потребность<Icon name="arrow" size={16} /></Link>}
      <div className="mobile-disclosure" ref={disclosure}><button type="button" ref={toggle} className="icon-button" aria-label={open ? "Закрыть навигацию" : "Открыть навигацию"} aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen(value => !value)}><Icon name={open ? "close" : "menu"} /></button>{open && <nav className="mobile-links" id={id} aria-label="Навигация по сайту" onClick={event => { if ((event.target as HTMLElement).closest("a")) setOpen(false); }}>{workLinks}{!admin && <><ActiveLink href="/needs/new">Разместить потребность</ActiveLink><ActiveLink href="/support">Поддержка</ActiveLink></>}</nav>}</div>
    </div>
  </div>;
}

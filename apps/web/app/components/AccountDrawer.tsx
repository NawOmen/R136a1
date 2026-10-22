"use client";

import Link from "next/link";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ActiveLink } from "./ActiveLink";
import { Icon } from "./Icon";
import { api, AUTH_CHANGED_EVENT, clearToken, getToken, User } from "../lib/api";

import { applyTheme, savedTheme, THEME_CHANGED_EVENT, Theme } from "../lib/theme";

const drawerTransitionMs = 220;

export function AccountDrawer() {
  const pathname = usePathname();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [open, setOpen] = useState(false);
  const [present, setPresent] = useState(false);
  const [animated, setAnimated] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function cancelExit() {
    if (exitTimer.current !== null) { clearTimeout(exitTimer.current); exitTimer.current = null; }
  }
  function showDrawer(pointerInitiated: boolean) {
    cancelExit();
    setAnimated(pointerInitiated && !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    setPresent(true); setOpen(true);
  }
  function closeDrawer(pointerInitiated = false) {
    cancelExit();
    const shouldAnimate = pointerInitiated && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setAnimated(shouldAnimate); setOpen(false);
    if (shouldAnimate) exitTimer.current = setTimeout(() => { exitTimer.current = null; setPresent(false); }, drawerTransitionMs);
    else setPresent(false);
  }
  useEffect(() => () => cancelExit(), []);
  useEffect(() => {
    if (!open) return;
    const drawer = drawerRef.current;
    // Safari pointer clicks do not focus buttons; retain the actual opener.
    const trigger = triggerRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer?.querySelector<HTMLButtonElement>("button")?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeDrawer(); }
      if (event.key !== "Tab") return;
      const items = drawer?.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
      if (!items?.length) return;
      const first = items[0], last = items[items.length - 1];
      // A pending action can disable the focused button. Keep focus inside
      // even when that element is no longer in the current tab order.
      const outsideTabOrder = !Array.from(items).some(item => item === document.activeElement);
      if (event.shiftKey && (outsideTabOrder || document.activeElement === first)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (outsideTabOrder || document.activeElement === last)) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", handleKey); if (trigger?.isConnected && !trigger.disabled) trigger.focus({ preventScroll: true }); };
  }, [open]);
  const [user, setUser] = useState<User | null>(null);
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    closeDrawer();
    let generation = 0;
    const sync = () => {
      const current = ++generation;
      const token = getToken();
      if (!token) { setUser(null); closeDrawer(); return; }
      void api.me(token).then(result => { if (current === generation) setUser(result.user); }).catch(() => { if (current === generation) { setUser(null); closeDrawer(); } });
    };
    const saved = savedTheme();
    setTheme(saved); document.documentElement.dataset.theme = saved; sync();
    const syncTheme = () => setTheme(savedTheme());
    window.addEventListener(THEME_CHANGED_EVENT, syncTheme);
    window.addEventListener("storage", syncTheme);
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { generation++; window.removeEventListener(THEME_CHANGED_EVENT, syncTheme); window.removeEventListener("storage", syncTheme); window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [pathname]);
  function toggleTheme() { const next = theme === "light" ? "dark" : "light"; setTheme(next); applyTheme(next); }
  async function logout() {
    if (signingOut || !window.confirm("Выйти из аккаунта на всех устройствах?")) return;
    const token = getToken(); setSigningOut(true); setLogoutError("");
    try {
      if (token) await api.logout(token);
      clearToken(); window.localStorage.removeItem("porukam-work-mode"); closeDrawer(); router.replace("/"); router.refresh();
    } catch {setLogoutError("Не удалось завершить сеансы. Повторите выход.");}
    finally {setSigningOut(false);}
  }
  return <div className="account-control">
    <button className="icon-button theme-toggle" type="button" onClick={toggleTheme} aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"} title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}><Icon name={theme === "dark" ? "sun" : "moon"} size={19} /></button>
    {!user && <><Link className="account-login" href="/login">Войти</Link><Link className="btn btn-outline-primary btn-sm" href="/register">Регистрация</Link></>}
    {user && <button ref={triggerRef} className="account-avatar" type="button" aria-label="Открыть личный кабинет" aria-expanded={open} aria-controls={open ? "account-drawer" : undefined} onClick={event => showDrawer(event.detail !== 0)}>{user.first_name.slice(0, 1)}{user.last_name.slice(0, 1)}</button>}
    {present && user && createPortal(<><button className="drawer-backdrop" tabIndex={-1} aria-label="Закрыть панель" aria-hidden={!open || undefined} disabled={!open} data-state={open ? "open" : "closed"} data-motion={animated ? "animated" : "instant"} onClick={event => closeDrawer(event.detail !== 0)} /><aside ref={drawerRef} id="account-drawer" role="dialog" aria-modal={open || undefined} aria-hidden={!open || undefined} inert={!open} className="account-drawer" aria-label="Меню аккаунта" data-state={open ? "open" : "closed"} data-motion={animated ? "animated" : "instant"}>
      <div className="company-row"><div><h2>{user.first_name} {user.last_name}</h2><span className="hint">{user.email}</span></div><button className="drawer-close" aria-label="Закрыть" onClick={event => closeDrawer(event.detail !== 0)}><Icon name="close" /></button></div>
      {logoutError && <p role="alert">{logoutError}</p>}<nav onClick={(event) => { if ((event.target as HTMLElement).closest("a")) closeDrawer(); }}><ActiveLink href={user.is_marketplace_admin ? "/admin" : "/dashboard"}>Личный кабинет</ActiveLink>{(user.is_category_editor || user.is_marketplace_admin) && <ActiveLink href="/editor">Кабинет редактора</ActiveLink>}{!user.is_marketplace_admin && <><ActiveLink href="/coalitions">Коалиции</ActiveLink><ActiveLink href="/deals">Сделки</ActiveLink></>}<ActiveLink href="/notifications">Уведомления</ActiveLink><ActiveLink href="/settings">Настройки</ActiveLink>{!user.is_marketplace_admin && <ActiveLink href="/support">Поддержка</ActiveLink>}<button type="button" className="toggle-motion" onClick={toggleTheme}>Тема: {theme === "dark" ? "тёмная" : "светлая"}</button><button className="drawer-logout" type="button" disabled={signingOut} onClick={() => void logout()}>{signingOut ? "Выходим…" : "Выйти"}</button></nav>
    </aside></>, document.body)}
  </div>;
}

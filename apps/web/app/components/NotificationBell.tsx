"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { getToken } from "../lib/api";
import { marketplace, Notification } from "../lib/marketplace";
import { notificationHref } from "../lib/notifications";
import { Icon } from "./Icon";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const pathname = usePathname();
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      const token = getToken(); if (!token) return;
      void marketplace.getNotifications(token).then(value => { if (active) { setItems(value); setError(""); } })
        .catch(() => { if (active) setError("Не удалось загрузить уведомления."); }).finally(() => { if (active) setLoading(false); });
    };
    refresh(); const timer = window.setInterval(refresh, 30000);
    return () => { active = false; clearInterval(timer); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLElement>(".notification-popover button, .notification-popover a")?.focus();
    const click = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", click); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", click); document.removeEventListener("keydown", key); };
  }, [open]);
  async function view(item: Notification) {
    const token = getToken(); if (!token || item.is_read) return;
    try { await marketplace.markNotificationRead(token, item.id); setItems(value => value.map(n => n.id === item.id ? { ...n, is_read: true } : n)); }
    catch { setError("Не удалось отметить прочитанным. Откройте уведомление повторно."); }
  }
  const unread = items.filter(item => !item.is_read).length;
  return <div className="notification-control" ref={root}>
    <button ref={trigger} className="icon-button notification-trigger" aria-label={`Уведомления${unread ? `, новых: ${unread}` : ""}`} aria-expanded={open} aria-controls={open ? "header-notifications" : undefined} onClick={() => setOpen(v => !v)}><Icon name="bell" />{unread > 0 && <span className="notification-dot" />}</button>
    {open && <section id="header-notifications" className="notification-popover" aria-label="Уведомления">
      <div className="company-row"><h2>Уведомления</h2><button className="icon-button" aria-label="Закрыть уведомления" onClick={() => { setOpen(false); trigger.current?.focus(); }}><Icon name="close" /></button></div>
      {error && <p role="alert">{error}</p>}
      {loading ? <p role="status">Загружаем…</p> : items.length ? <ul>{items.slice(0, 8).map(item => <li key={item.id}><a href={notificationHref(item)} className={item.is_read ? "" : "unread"} onClick={() => { void view(item); setOpen(false); }}>{item.message}</a></li>)}</ul> : <p className="hint">Новых событий пока нет.</p>}
      <Link className="notification-all" href="/notifications">Все уведомления →</Link>
    </section>}
  </div>;
}

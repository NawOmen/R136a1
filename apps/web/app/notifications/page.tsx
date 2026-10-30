"use client";

// Уведомления (GET /notifications): список, «Прочитать» и «Прочитать все».

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { ApiError, marketplace, Notification } from "../lib/marketplace";
import { notificationHref } from "../lib/notifications";
import { useMe } from "../lib/useMe";

export default function NotificationsPage() {
  useMe(); // проверка входа
  const [retry, setRetry] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    let active = true; setLoading(true); setError(null);
    marketplace
      .getNotifications(token)
      .then(items => {if(active) setNotifications(items);})
      .catch((err: unknown) =>
        active && setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить уведомления."),
      )
      .finally(() => {if(active) setLoading(false);});
    return () => {active=false;};
  }, [retry]);

  async function handleRead(notification: Notification) {
    const token = getToken();
    if (!token || notification.is_read) return;
    setBusyId(notification.id);
    setError(null);
    try {
      await marketplace.markNotificationRead(token, notification.id);
      setNotifications((current) =>
        current.map((item) => (item.id === notification.id ? { ...item, is_read: true } : item)),
      );
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось отметить уведомление.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReadAll() {
    const token = getToken();
    if (!token) return;
    setMarkingAll(true);
    setError(null);
    try {
      await marketplace.markAllNotificationsRead(token);
      setNotifications((current) => current.map((item) => ({ ...item, is_read: true })));
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось отметить уведомления.");
    } finally {
      setMarkingAll(false);
    }
  }

  const unread = notifications.filter((item) => !item.is_read).length;

  if (loading) return <p className="hint">Загрузка...</p>;

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Уведомления</h1>
        <div className="actions">
          {unread > 0 && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={markingAll || busyId !== null}
              onClick={() => void handleReadAll()}
            >
              {markingAll ? "..." : "Прочитать все"}
            </button>
          )}
          <Link href="/dashboard" className="btn btn-secondary btn-sm">
            В личный кабинет
          </Link>
        </div>
      </div>
      <p className="subtitle">
        {unread > 0 ? `Непрочитанных: ${unread}` : "Все уведомления прочитаны"}
      </p>

      {error && <div className="alert alert-error" role="alert">{error}<button type="button" className="btn btn-secondary" onClick={() => setRetry(value => value+1)}>Повторить загрузку</button></div>}

      {notifications.length === 0 && !error ? (
        <p className="hint">Уведомлений пока нет.</p>
      ) : (
        <ul className="company-list">
          {notifications.map((notification) => (
            <li key={notification.id} id={`notification-${notification.id}`}>
              <a className="card notification-card" href={notificationHref(notification)} onClick={() => void handleRead(notification)}>
                <span className={`badge ${notification.is_read ? "badge-read" : "badge-unread"}`}>{notification.is_read ? "Прочитано" : "Новое"}</span>
                <span className="notification-message">{notification.message}</span>
                <span className="notification-card__open">Открыть событие <span aria-hidden="true">→</span></span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

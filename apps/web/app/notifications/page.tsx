"use client";

// Уведомления (GET /notifications): список, «Прочитать» и «Прочитать все».

import { russianMessage } from "../lib/russianMessages";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getToken } from "../lib/api";
import { ApiError, marketplace, Notification } from "../lib/marketplace";
import { useMe } from "../lib/useMe";

export default function NotificationsPage() {
  useMe(); // проверка входа
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    marketplace
      .getNotifications(token)
      .then(setNotifications)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить уведомления."),
      )
      .finally(() => setLoading(false));
  }, []);

  async function handleRead(notification: Notification) {
    const token = getToken();
    if (!token) return;
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
              disabled={markingAll}
              onClick={() => void handleReadAll()}
            >
              {markingAll ? "..." : "Прочитать все"}
            </button>
          )}
          <Link href="/dashboard" className="btn btn-secondary btn-sm">
            На главную
          </Link>
        </div>
      </div>
      <p className="subtitle">
        {unread > 0 ? `Непрочитанных: ${unread}` : "Все уведомления прочитаны"}
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      {notifications.length === 0 ? (
        <p className="hint">Уведомлений пока нет.</p>
      ) : (
        <ul className="company-list">
          {notifications.map((notification) => (
            <li key={notification.id} className="card">
              <div className="company-row">
                <span className={`badge ${notification.is_read ? "badge-read" : "badge-unread"}`}>
                  {notification.is_read ? "Прочитано" : "Новое"}
                </span>
                {!notification.is_read && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={busyId === notification.id}
                    onClick={() => void handleRead(notification)}
                  >
                    {busyId === notification.id ? "..." : "Прочитать"}
                  </button>
                )}
              </div>
              <p style={{ margin: "10px 0 0" }}>{notification.message}</p>
              <p className="hint mode-hint">Тип: {notification.type}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

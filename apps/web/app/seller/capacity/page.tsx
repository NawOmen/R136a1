"use client";

// Календарь мощностей (GET/PUT /companies/{id}/capacity).
// Таблица на ближайшие 10 дней, поле available_units на каждую дату.

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getToken } from "../../lib/api";
import { ApiError, formatUnits, marketplace } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

const DAYS_COUNT = 30;

function formatDateKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export default function SellerCapacityPage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const dates = useMemo(() => {
    const today = new Date();
    return Array.from({ length: DAYS_COUNT }, (_, index) => formatDateKey(addDays(today, index)));
  }, []);

  const [reserved, setReserved] = useState<Record<string, number>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false); setValues({}); setReserved({}); setSaved(false);
    setError(null);
    marketplace
      .getCapacity(token, companyId)
      .then((entries) => {
        if (cancelled) return;
        const next: Record<string, string> = {};
        for (const entry of entries) {
          if (dates.includes(entry.date)) next[entry.date] = String(entry.available_units);
        }
        setValues(next);
        setReserved(Object.fromEntries(entries.map(entry=>[entry.date, entry.reserved_units ?? 0])));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Не удалось загрузить мощности.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, dates]);

  async function handleSave() {
    const token = getToken();
    if (!token || !company) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const entries = dates.map((date) => ({
        date,
        available_units: Number(values[date] || 0),
      }));
      if (entries.some(entry=>!Number.isSafeInteger(entry.available_units) || entry.available_units < 0)) throw new Error("Укажите целое количество единиц для каждого дня.");
      await marketplace.updateCapacity(token, company.id, entries);
      const updated = await marketplace.getCapacity(token, company.id);
      setReserved(Object.fromEntries(updated.map(entry=>[entry.date, entry.reserved_units ?? 0])));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить мощности.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Мощности</h1>
        <div className="alert alert-error">{meError}</div>
        <Link href="/login" className="btn btn-secondary">
          На страницу входа
        </Link>
      </div>
    );
  }

  if (available.length === 0) {
    return (
      <div>
        <h1 className="page-title">Мощности</h1>
        <div className="alert alert-error">
          У вас нет компании с правом «Продаю». Создайте компанию и включите режим продажи.
        </div>
        <div className="actions">
          <Link href="/company/new" className="btn btn-primary">
            Создать компанию
          </Link>
          <Link href="/dashboard" className="btn btn-secondary">
            На главную
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Мощности</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Общая и свободная мощность производства по дням (ближайшие {DAYS_COUNT} дней)</p>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="seller_company">Компания</label>
          <select id="seller_company" value={companyId} disabled={saving} onChange={(event) => setCompanyId(event.target.value)}>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {saved && <div className="alert alert-success">Мощности сохранены.</div>}
      {error && <div className="alert alert-error">{error}</div>}

      <section className="card">
        {!loaded ? (
          <p className="hint">Загрузка календаря...</p>
        ) : (
          <>
            <table className="capacity-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Всего, ед.</th><th>Занято, ед.</th><th>Свободно, ед.</th>
                </tr>
              </thead>
              <tbody>
                {dates.map((date) => (
                  <tr key={date}>
                    <td>{date}</td>
                    <td>
                      <input
                        type="number"
                        min={reserved[date] ?? 0}
                        step="1"
                        aria-label={`Общая мощность на ${date}`}
                        value={values[date] ?? ""}
                        placeholder="0"
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [date]: event.target.value }))
                        }
                      />
                    </td><td>{reserved[date] ?? 0}</td><td>{Math.max(0, Number(values[date] || 0) - (reserved[date] ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="hint mode-hint">
              Например, {formatUnits(4800)} — общий объём производства в этот день. Занятый объём включает заказы, удержания и уже выполненную работу. Уменьшить общую мощность ниже занятого объёма нельзя.
            </p>
            <div className="actions">
              <button type="button" className="btn btn-primary" disabled={saving} onClick={() => void handleSave()}>
                {saving ? "Сохраняем..." : "Сохранить"}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

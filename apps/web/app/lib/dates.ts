/** Calendar dates keep their day across time zones. API values remain ISO. */
export function formatDate(value: string | null | undefined, empty = "—"): string {
  if (!value) return empty;
  // Timestamp-only date labels retain the viewer's day, as date-time labels do.
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" }).format(date) : empty;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match || !validDay(+match[1], +match[2], +match[3])) return empty;
  return `${match[3]}.${match[2]}.${match[1].slice(-2)}`;
}

function validDay(year: number, month: number, day: number) {
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/** Keep the event time, using the viewer's time zone as before. */
export function formatDateTime(value: string | null | undefined, empty = "—"): string {
  if (!value) return empty;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value, empty);
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return empty;
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function formatMonth(value: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  return match && +match[2] >= 1 && +match[2] <= 12
    ? new Intl.DateTimeFormat("ru-RU", { month: "long", year: "2-digit", timeZone: "UTC" }).format(new Date(`${value}-01T00:00:00Z`)) : "Период не указан";
}

/** Short-year business dates use 2000–2099; four digits are also accepted. */
export function parseDateInput(value: string): string {
  const match = /^(\d{2})\.(\d{2})\.(\d{2}|\d{4})$/.exec(value);
  if (!match) return "";
  const year = match[3].length === 2 ? 2000 + +match[3] : +match[3];
  return validDay(year, +match[2], +match[1]) ? `${String(year).padStart(4, "0")}-${match[2]}-${match[1]}` : "";
}

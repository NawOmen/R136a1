/** Presentation only: API payloads and native date inputs retain ISO values. */
const dateFormat = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
const timeFormat = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });
export function formatDate(value: string | Date | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  // Calendar-only dates must never move across a timezone boundary.
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-");
    const parsed = new Date(`${value}T12:00:00Z`);
    if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) return fallback;
    return `${day}.${month}.${year.slice(-2)}`;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : dateFormat.format(date);
}
export function formatDateTime(value: string | Date | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : `${formatDate(date)}, ${timeFormat.format(date)}`;
}

"use client";

import { useEffect, useRef, useState, type InputHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { formatDate, parseDateInput } from "../lib/dates";
import { Icon } from "./Icon";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange" | "min" | "max"> & {
  value: string; onValueChange: (value: string) => void; min?: string; max?: string;
};
const iso = (date: Date) => date.toISOString().slice(0, 10);

/** Russian presentation and calendar, independent of the browser's UI language. */
export function DateInput({ value, onValueChange, min, max, ...props }: Props) {
  const input = useRef<HTMLInputElement>(null), trigger = useRef<HTMLButtonElement>(null), popup = useRef<HTMLDivElement>(null);
  const echo = useRef(value);
  const [text, setText] = useState(() => formatDate(value, ""));
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState("");
  const [position, setPosition] = useState({ top: 0, left: 0 });
  useEffect(() => {
    if (value !== echo.current) { echo.current = value; setText(formatDate(value, "")); }
  }, [value]);
  useEffect(() => {
    const parsed = text === formatDate(value, "") ? value : parseDateInput(text);
    input.current?.setCustomValidity(text && !parsed ? "Введите дату в формате дд.мм.гг." : parsed && min && parsed < min
      ? `Укажите дату не раньше ${formatDate(min)}.` : parsed && max && parsed > max ? `Укажите дату не позже ${formatDate(max)}.` : "");
  }, [text, value, min, max]);
  useEffect(() => {
    if (!open) return;
    const place = () => { const box = input.current!.getBoundingClientRect(), height = popup.current?.getBoundingClientRect().height ?? 350; setPosition({ left: Math.max(8, Math.min(box.left, innerWidth - 296)), top: Math.max(8, Math.min(box.bottom + 6, innerHeight - height - 8)) }); };
    const dismiss = (event: PointerEvent) => { if (!popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); } };
    place();
    const selected = popup.current?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]:not(:disabled)') ?? popup.current?.querySelector<HTMLButtonElement>('.date-calendar__grid button:not(:disabled)');
    if (!popup.current?.contains(document.activeElement)) selected?.focus({ preventScroll: true });
    window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", dismiss); document.addEventListener("keydown", escape);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", escape); };
  }, [open, month]);
  const choose = (next: string) => {
    if (input.current?.matches(":disabled")) { setOpen(false); return; }
    echo.current = next; setText(formatDate(next, "")); onValueChange(next); setOpen(false); input.current?.focus({ preventScroll: true });
  };
  const date = new Date(`${month || "2000-01"}-01T00:00:00Z`);
  const first = (date.getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  const title = new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" }).format(date);
  return <span className="date-input">
    <input {...props} ref={input} type="text" inputMode="numeric" placeholder="дд.мм.гг" maxLength={10} value={text} onChange={event => {
      let next = event.target.value;
      const digits = next.replace(/[.,]/g, "");
      // Numeric phone keyboards need no punctuation key. Only append-format;
      // deletion and edits in the middle retain the user's caret and text.
      if (/^\d{0,8}$/.test(digits) && (/^\d{6}(\d{2})?$/.test(next) || next.length > text.length && event.target.selectionStart === next.length)) {
        next = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)].filter(Boolean).join(".");
      }
      setText(next);
      const parsed = next === formatDate(value, "") ? value : parseDateInput(next);
      echo.current = parsed; onValueChange(parsed);
    }} onBlur={event => { if (value) setText(formatDate(value, "")); props.onBlur?.(event); }} />
    <button ref={trigger} type="button" disabled={props.disabled} className="date-input__trigger" aria-label="Открыть календарь" aria-expanded={open} onClick={() => {
      const today = new Date();
      const current = value || `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      setMonth(current.slice(0, 7)); setOpen(previous => !previous);
    }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M7 3v4m10-4v4M3 11h18" /></svg></button>
    {open && createPortal(<div ref={popup} className="date-calendar" role="dialog" aria-label="Выбрать дату" style={position}>
      <div className="date-calendar__head"><button type="button" aria-label="Предыдущий месяц" onClick={() => setMonth(iso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() - 1, 1))).slice(0, 7))}><Icon name="arrow" size={16} style={{ transform: "rotate(180deg)" }} /></button><strong aria-live="polite">{title}</strong><button type="button" aria-label="Следующий месяц" onClick={() => setMonth(iso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1))).slice(0, 7))}><Icon name="arrow" size={16} /></button></div>
      <div className="date-calendar__grid">{["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map(day => <span key={day}>{day}</span>)}
        {Array.from({ length: first }, (_, i) => <span key={`blank-${i}`} />)}
        {Array.from({ length: count }, (_, i) => {
          const next = `${month}-${String(i + 1).padStart(2, "0")}`;
          return <button key={next} type="button" aria-label={formatDate(next)} aria-pressed={value === next} disabled={Boolean(min && next < min || max && next > max)} onClick={() => choose(next)}>{i + 1}</button>;
        })}
      </div>
      <button type="button" className="date-calendar__close" onClick={() => { setOpen(false); trigger.current?.focus(); }}>Закрыть календарь</button>
    </div>, document.body)}
  </span>;
}

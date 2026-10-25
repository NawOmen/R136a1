"use client";

import { useEffect, useState } from "react";

export function SearchInput({ demand, value, onChange }: { demand: boolean; value: string; onChange: (value: string) => void }) {
  const [focused, setFocused] = useState(false);
  const [example, setExample] = useState("");
  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const phrases = demand ? ["Упаковка для производства", "Рабочая одежда"] : ["Бумажные стаканы", "Коробки для отправки", "Рабочая одежда"];
    let timer: ReturnType<typeof setTimeout> | undefined;
    let phrase = 0, length = 0, deleting = false;
    const tick = () => {
      if (document.hidden || motion.matches || focused || value) return;
      length += deleting ? -1 : 1;
      setExample(phrases[phrase].slice(0, length));
      let delay = deleting ? 55 : 105;
      if (length === phrases[phrase].length) { deleting = true; delay = 2200; }
      else if (length === 0) { deleting = false; phrase = (phrase + 1) % phrases.length; delay = 600; }
      timer = setTimeout(tick, delay);
    };
    const restart = () => {
      clearTimeout(timer); setExample(""); length = 0; deleting = false;
      if (!motion.matches && !focused && !value && !document.hidden) timer = setTimeout(tick, 1400);
    };
    restart();
    motion.addEventListener("change", restart);
    document.addEventListener("visibilitychange", restart);
    return () => { clearTimeout(timer); motion.removeEventListener("change", restart); document.removeEventListener("visibilitychange", restart); };
  }, [demand, focused, value]);
  return <input name="q" aria-label="Поиск по маркетплейсу" value={value} onChange={event => onChange(event.target.value)} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} placeholder={!focused && example ? example : demand ? "Найти потребность" : "Найти товар или категорию"} />;
}

"use client";

import { ReactNode, useEffect, useRef } from "react";

// Color reflects field format, never business feasibility or source truth.
export function ValidatedFields({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    ref.current?.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea").forEach((field) => {
      const empty = !field.value.trim() && !field.validity.badInput;
      const invalid = !empty && !field.validity.valid;
      field.dataset.validation = empty ? "empty" : invalid ? "invalid" : "valid";
      field.setAttribute("aria-invalid", String(invalid));
      field.setAttribute("aria-describedby", "manual-format-hint");
    });
  });
  return <section ref={ref} className="manual-requirements" aria-labelledby="manual-heading">
    <h2 id="manual-heading">Проверьте карточку</h2>
    <p id="manual-format-hint" className="hint">Проверьте количество, срок и адрес. Исправьте выделенные ошибки перед отправкой.</p>
    {children}
  </section>;
}

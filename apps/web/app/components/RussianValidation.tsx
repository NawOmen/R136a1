"use client";
import { useEffect } from "react";

/** Native validation follows the browser locale unless a message is supplied. */
export function RussianValidation() {
  useEffect(() => {
    const control = (value: EventTarget | null): HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null =>
      value instanceof HTMLInputElement || value instanceof HTMLSelectElement || value instanceof HTMLTextAreaElement ? value : null;
    const localized = new WeakSet<HTMLElement>();
    const invalid = (event: Event) => {
      const field = control(event.target); if (!field || field.validity.customError) return;
      const state = field.validity;
      localized.add(field);
      field.setCustomValidity(state.valueMissing ? "Заполните обязательное поле." :
        state.typeMismatch ? (field instanceof HTMLInputElement && field.type === "email" ? "Введите корректный адрес электронной почты." : "Проверьте формат значения.") :
        state.rangeUnderflow ? "Значение меньше допустимого минимума." :
        state.rangeOverflow ? "Значение больше допустимого максимума." :
        state.stepMismatch ? "Укажите значение с допустимым шагом." :
        state.tooShort ? "Значение слишком короткое." :
        state.tooLong ? "Значение слишком длинное." : "Проверьте введённое значение.");
    };
    const clear = (event: Event) => {
      const field = control(event.target);
      if (field && localized.has(field)) { field.setCustomValidity(""); localized.delete(field); }
    };
    document.addEventListener("invalid", invalid, true);
    document.addEventListener("input", clear, true);
    document.addEventListener("change", clear, true);
    return () => { document.removeEventListener("invalid", invalid, true); document.removeEventListener("input", clear, true); document.removeEventListener("change", clear, true); };
  }, []);
  return null;
}

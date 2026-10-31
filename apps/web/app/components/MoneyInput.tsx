"use client";

import type { ComponentProps } from "react";
import { moneyInputValue } from "../lib/money";

type Props = Omit<ComponentProps<"input">, "type" | "step">;

/** New entries use kopecks; opening a legacy record never rewrites its stored value. */
export default function MoneyInput({ value, defaultValue, onChange, title, ...props }: Props) {
  const shown = typeof value === "string" || typeof value === "number" ? moneyInputValue(value) : value;
  const roundedLegacy = value != null && String(shown) !== String(value) && /[.,]\d{3,}/.test(String(value));
  // A valid saved subkopeck price may display as 0.00. It must remain editable
  // without forcing a price change when the user only edits other product data.
  const minimum = roundedLegacy && /^0(?:\.0{1,2})?$/.test(String(shown)) ? "0" : props.min;
  return <input {...props} min={minimum} type="number" inputMode="decimal" step="0.01"
    value={shown} defaultValue={typeof defaultValue === "string" || typeof defaultValue === "number" ? moneyInputValue(defaultValue) : defaultValue}
    title={title ?? (roundedLegacy ? "Сохранённая сумма показана с округлением до копеек. Изменение поля задаст новую сумму." : undefined)}
    onChange={event => {
      const next = moneyInputValue(event.currentTarget.value);
      if (next !== event.currentTarget.value) event.currentTarget.value = next;
      onChange?.(event);
    }} />;
}

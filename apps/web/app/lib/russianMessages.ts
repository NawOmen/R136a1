/** Translate system messages at the presentation boundary; never rewrite user documents. */
export function russianMessage(value: unknown, fallback = "Не удалось выполнить действие. Повторите попытку."): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  const message = value.replace(/^Value error,\s*/i, "").trim();
  if (/failed to fetch|fetch failed|networkerror|network request failed|load failed/i.test(message)) return "Не удалось связаться с сервером. Проверьте соединение и повторите попытку.";
  if (!/[а-яё]/i.test(message)) return fallback;
  return message.replace(/Неверный email/gi, "Неверная электронная почта").replace(/\bemail\b/gi, "электронная почта");
}

export function validationMessage(item: { loc?: unknown[]; msg?: string; type?: string; ctx?: Record<string, unknown> }, labels: Record<string, string>): string {
  const field = String(item.loc?.at(-1) ?? "");
  const label = labels[field] ?? (/[а-яё]/i.test(field) ? field : "Значение");
  const type = item.type ?? "";
  const message = item.msg ?? "";
  if (type === "missing" || message === "Field required") return `«${label}»: заполните обязательное поле`;
  if (type.includes("too_short") || /at least/i.test(message)) return `«${label}»: слишком короткое значение${item.ctx?.min_length ? `, минимум ${item.ctx.min_length} символов` : ""}`;
  if (type.includes("too_long") || /at most/i.test(message)) return `«${label}»: слишком длинное значение${item.ctx?.max_length ? `, максимум ${item.ctx.max_length} символов` : ""}`;
  if (/email/i.test(message)) return "Введите корректный адрес электронной почты";
  if (type.includes("greater_than")) return `«${label}»: значение должно быть ${type.endsWith("equal") ? "не меньше" : "больше"} ${item.ctx?.ge ?? item.ctx?.gt ?? "допустимого минимума"}`;
  if (type.includes("less_than")) return `«${label}»: значение должно быть ${type.endsWith("equal") ? "не больше" : "меньше"} ${item.ctx?.le ?? item.ctx?.lt ?? "допустимого максимума"}`;
  if (type.includes("int") || type.includes("float") || type.includes("decimal")) return `«${label}»: введите корректное число`;
  if (type.includes("date")) return `«${label}»: введите корректную дату`;
  if (type.includes("bool")) return `«${label}»: выберите «Да» или «Нет»`;
  if (type.includes("uuid")) return `«${label}»: выберите существующую запись`;
  if (type === "literal_error" || type === "enum") return `«${label}»: выберите допустимый вариант`;
  return `«${label}»: ${russianMessage(message, "проверьте формат и допустимое значение")}`;
}

export async function russianFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try { return await fetch(input, init); }
  catch { throw new Error("Не удалось связаться с сервером. Проверьте соединение и повторите попытку."); }
}

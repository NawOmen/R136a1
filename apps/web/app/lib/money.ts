/** v3 transmits exact decimal strings; numbers remain accepted for legacy callers. */
export type Money = string | number;
const SCALE = BigInt(10) ** BigInt(12);
export function scaledMoney(value: Money): bigint {
  const text = (typeof value === "number" ? value.toFixed(12).replace(/0+$/, "").replace(/\.$/, "") : value).trim().replace(',', '.');
  if (!/^-?\d+(\.\d{1,12})?$/.test(text)) throw new Error('Некорректная сумма');
  const negative = text.startsWith('-');
  const [whole, part = ''] = text.replace('-', '').split('.');
  const result = BigInt(whole) * SCALE + BigInt(part.padEnd(12, '0'));
  return negative ? -result : result;
}
export function moneyString(value: bigint): string {
  const sign = value < BigInt(0) ? '-' : '';
  const positive = value < BigInt(0) ? -value : value;
  return `${sign}${positive / SCALE}.${(positive % SCALE).toString().padStart(12, '0')}`;
}
export function lineAmount(price: Money, units: Money): string {
  const raw = scaledMoney(price) * scaledMoney(units);
  const cent = SCALE * SCALE / BigInt(100);
  const positive = raw < BigInt(0) ? -raw : raw;
  const rounded = ((positive + cent / BigInt(2)) / cent) * cent;
  return moneyString((raw < BigInt(0) ? -rounded : rounded) / SCALE);
}
/** Editable fields may be empty or incomplete; a preview must not break the form. */
export function previewLineAmount(price: Money, units: Money): string | null {
  try { return lineAmount(price, units); } catch { return null; }
}
export function displayMoney(value: Money | null | undefined, precision = 2): string {
  if (value == null) return '—';
  precision = Math.max(0, Math.min(2, Math.trunc(precision) || 0));
  try {
    const raw = scaledMoney(value);
    const positive = raw < BigInt(0) ? -raw : raw;
    const quantum = BigInt(10) ** BigInt(12 - precision);
    const rounded = ((positive + quantum / BigInt(2)) / quantum) * quantum;
    if (precision === 2 && positive > BigInt(0) && rounded === BigInt(0)) return raw < BigInt(0) ? 'больше −0,01 ₽' : 'менее 0,01 ₽';
    const whole = (rounded / SCALE).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
    const fraction = (rounded % SCALE).toString().padStart(12, '0').slice(0, precision).replace(/0+$/, '');
    return `${raw < BigInt(0) ? '−' : ''}${whole}${fraction ? ',' + fraction : ''} ₽`;
  } catch { return '—'; }
}

/** Round a new monetary entry HALF_UP using decimal digits, without binary floats. */
export function moneyInputValue(value: Money | null | undefined): string {
  if (value == null) return "";
  const text = String(value).trim().replace(",", ".");
  const parts = /^(-?)(\d+)(?:\.(\d*))?$/.exec(text);
  if (!parts || (parts[3]?.length ?? 0) <= 2) return text;
  const [, sign, whole, fraction] = parts;
  let cents = BigInt(whole) * BigInt(100) + BigInt(fraction.slice(0, 2));
  if (fraction[2] >= "5") cents += BigInt(1);
  return `${sign}${cents / BigInt(100)}.${(cents % BigInt(100)).toString().padStart(2, "0")}`;
}

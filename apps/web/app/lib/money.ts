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
export function lineAmount(price: Money, units: number): string {
  const raw = scaledMoney(price) * BigInt(units);
  const cent = SCALE / BigInt(100);
  const positive = raw < BigInt(0) ? -raw : raw;
  const rounded = ((positive + cent / BigInt(2)) / cent) * cent;
  return moneyString(raw < BigInt(0) ? -rounded : rounded);
}
export function displayMoney(value: Money | null | undefined, precision = 2): string {
  if (value == null) return '—';
  try {
    const raw = scaledMoney(value);
    const positive = raw < BigInt(0) ? -raw : raw;
    const quantum = BigInt(10) ** BigInt(12 - precision);
    const rounded = ((positive + quantum / BigInt(2)) / quantum) * quantum;
    const whole = (rounded / SCALE).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
    const fraction = (rounded % SCALE).toString().padStart(12, '0').slice(0, precision).replace(/0+$/, '');
    return `${raw < BigInt(0) ? '−' : ''}${whole}${fraction ? ',' + fraction : ''} ₽`;
  } catch { return '—'; }
}

import { CAPABILITY_FIELDS } from "../lib/capabilities";

export function CapabilityDescription({ details }: { details: Record<string, unknown> }) {
  const labels: Record<string, string> = { manufacturer: "Производство на заказ", stock_supplier: "Поставка со склада", both: "Производство и склад" };
  return <div>
    {typeof details.business_kind === "string" && <p>{labels[String(details.business_kind)] ?? "Уточните вид деятельности"}</p>}
    <dl>{CAPABILITY_FIELDS.filter((field) => details[field.key]).map((field) => <div key={field.key}>
      <dt><strong>{field.label}</strong></dt><dd>{String(details[field.key])}</dd>
    </div>)}</dl>
  </div>;
}

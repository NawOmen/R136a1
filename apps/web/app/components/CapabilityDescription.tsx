import { CAPABILITY_FIELDS } from "../lib/capabilities";

export function CapabilityDescription({ details }: { details: Record<string, unknown> }) {
  const labels: Record<string, string> = { manufacturer: "Производство на заказ", stock_supplier: "Поставка со склада", both: "Производство и склад" };
  const fields = CAPABILITY_FIELDS.filter(field => details[field.key] != null && String(details[field.key]).trim());
  return <div className="capability-description">
    <dl className="capability-facts">
      {typeof details.business_kind === "string" && <div>
        <dt>Вид деятельности</dt><dd>{labels[details.business_kind] ?? "Уточните вид деятельности"}</dd>
      </div>}
      {fields.map(field => <div key={field.key}>
        <dt>{field.label}</dt><dd>{String(details[field.key])}</dd>
      </div>)}
    </dl>
  </div>;
}

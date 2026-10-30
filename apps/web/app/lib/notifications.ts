import type { Notification } from "./marketplace";

/** Never navigate to an external URL supplied in a notification response. */
export function notificationHref(item: Notification): string {
  const href = item.href;
  if (href?.split(/[?#]/)[0] !== "/notifications" && !["/needs", "/deals"].includes(href ?? "") && href?.startsWith("/") && !href.startsWith("//") && !/[\\\u0000-\u001f\u007f]/.test(href)) return href;
  const uuid = "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})";
  const deal = item.message.match(new RegExp("сделк[аеиу]\\s+" + uuid, "i"));
  if (deal) return `/deals?deal=${deal[1]}`;
  const need = item.message.match(new RegExp("потребност[ьи]\\s+" + uuid, "i"));
  if (need) return `/needs/${need[1]}`;
  if (item.type === "support_ticket_created") return "/admin#tickets";
  if (item.type.startsWith("support_")) return "/support";
  if (["offer_received", "offer_updated", "need_revision"].includes(item.type)) return "/needs";
  if (item.type === "offer_selected" || item.type.startsWith("deal_") || item.type === "replacement_activated") return "/deals";
  if (["reserve_invitation", "reserve_reconfirmation"].includes(item.type)) return "/seller/reserves";
  if (["producer_failure", "reserve_confirmation_required"].includes(item.type)) return "/resilience";
  if (item.type === "document_verification_changed") return "/dashboard";
  if (item.type === "market_demand_changed") return "/seller/requests";
  if (item.type === "market_supply_changed") return "/catalog";
  return "/dashboard";
}

"""Internal destinations for notifications; old records keep a useful section link."""
from urllib.parse import urlsplit


def default_notification_href(type_: str) -> str:
    if type_ == "support_ticket_created":
        return "/admin#tickets"
    if type_.startswith("support_"):
        return "/support"
    if type_ == "offer_received" or type_ == "need_revision":
        return "/needs"
    if type_ == "offer_selected" or type_.startswith("deal_") or type_ == "replacement_activated":
        return "/deals"
    if type_ in {"reserve_invitation", "reserve_reconfirmation"}:
        return "/seller/reserves"
    if type_ in {"producer_failure", "reserve_confirmation_required"}:
        return "/resilience"
    if type_ == "document_verification_changed":
        return "/dashboard"
    if type_ == "market_demand_changed":
        return "/seller/requests"
    if type_ == "market_supply_changed":
        return "/catalog"
    return "/notifications"


def internal_notification_href(href: str) -> str:
    parts = urlsplit(href)
    if (len(href) > 500 or not href.startswith("/") or href.startswith("//")
            or parts.scheme or parts.netloc or "\\" in href
            or any(ord(char) < 32 or ord(char) == 127 for char in href)):
        raise ValueError("Уведомление должно вести на внутреннюю страницу")
    return href

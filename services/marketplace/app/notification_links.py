"""Internal destinations for notifications; old records keep a useful section link."""
from urllib.parse import urlsplit


def default_notification_href(type_: str) -> str:
    if type_ == "support_ticket_created":
        return "/admin#tickets"
    if type_.startswith("support_"):
        return "/support"
    if type_ in {"offer_received", "offer_updated", "need_revision"}:
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
    return "/dashboard"


def internal_notification_href(href: str) -> str:
    parts = urlsplit(href)
    if (len(href) > 500 or not href.startswith("/") or href.startswith("//")
            or parts.scheme or parts.netloc or "\\" in href
            or any(ord(char) < 32 or ord(char) == 127 for char in href)):
        raise ValueError("Уведомление должно вести на внутреннюю страницу")
    return href


def message_notification_href(message: str) -> str | None:
    """Recover only explicitly labelled entity IDs from old notification text."""
    import re
    identifier = r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    deal = re.search(r'сделк[аеиу]\s+' + identifier, message, re.I)
    if deal:
        return '/deals?deal=' + deal[1]
    need = re.search(r'потребност[ьи]\s+' + identifier, message, re.I)
    if need:
        return '/needs/' + need[1]
    return None


async def resolved_notification_href(db, item):
    from sqlalchemy import text
    href = getattr(item, 'href', None)
    if href:
        try:
            safe = internal_notification_href(href)
            if urlsplit(safe).path != '/notifications' and safe not in {'/needs', '/deals'}:
                return safe
        except ValueError:
            pass
    explicit = message_notification_href(item.message)
    if explicit:
        return explicit
    created = getattr(item, 'created_at', None)
    # PostgreSQL transaction timestamps identify legacy events without guessing
    # the newest order; ambiguous events retain their section destination.
    if created and item.type in {'offer_received', 'offer_selected', 'offer_updated'}:
        if item.type == 'offer_selected':
            query = '''SELECT d.id FROM marketplace.deals d
                JOIN auth.company_members m ON m.company_id=d.seller_company_id
                WHERE m.user_id=:uid AND d.created_at=:created LIMIT 2'''
            rows = (await db.execute(text(query), {'uid': item.user_id, 'created': created})).all()
            if len(rows) == 1:
                return f'/deals?deal={rows[0][0]}'
        else:
            query = '''SELECT o.need_id,o.id FROM marketplace.offers o
                JOIN marketplace.needs n ON n.id=o.need_id
                JOIN auth.company_members m ON m.company_id=n.company_id
                WHERE m.user_id=:uid AND m.can_buy=true AND o.created_at=:created LIMIT 2'''
            rows = (await db.execute(text(query), {'uid': item.user_id, 'created': created})).all()
            if len(rows) == 1:
                return f'/needs/{rows[0][0]}#offer-{rows[0][1]}'
    if created and (item.type == 'supplier_message_received' or (item.type == 'info' and 'по запросу КП' in item.message)):
        query = '''SELECT r.id,r.need_id,r.buyer_company_id,r.seller_company_id,m.company_id
            FROM marketplace.supplier_request_messages s
            JOIN marketplace.supplier_requests r ON r.id=s.request_id
            JOIN auth.company_members m ON m.company_id IN (r.buyer_company_id,r.seller_company_id)
            WHERE m.user_id=:uid AND s.created_at=:created AND s.author_company_id<>m.company_id LIMIT 2'''
        rows = (await db.execute(text(query), {'uid': item.user_id, 'created': created})).all()
        if len(rows) == 1:
            row = rows[0]
            return (f'/seller/inquiries?company={row[3]}&request={row[0]}' if row[4] == row[3]
                    else f'/needs/{row[1]}/suppliers?request={row[0]}')
    return default_notification_href(item.type)

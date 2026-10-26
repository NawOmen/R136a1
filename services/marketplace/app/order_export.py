"""One-way CommerceML 2.10 order export from frozen contractual data only."""
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from decimal import Decimal

from fastapi import HTTPException
from .category_units import order_unit
from .money import amount, decimal

NAMESPACE = "urn:1C.ru:commerceml_2"
ET.register_namespace("", NAMESPACE)


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
    for row in rows:
        writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(("=", "+", "-", "@")) or str(v).startswith(("\t", "\r", "\n")) else str(v) for v in row])
    return stream.getvalue().encode("utf-8-sig")


def agreed_lines(deal):
    snapshot = deal.commercial_snapshot or {}
    estimate = snapshot.get("estimate") or {}
    need = snapshot.get("need") or {}
    if not estimate.get("complete") or not need.get("characteristics") or deal.status == "cancelled":
        raise HTTPException(409, "Нет полной сохранённой спецификации заказа либо заказ отменён")
    lines = [line for line in estimate.get("lines", []) if not line.get("conditional") and line.get("amount_rub") is not None and (decimal(line["amount_rub"]) != 0 or line["code"] == "goods")]
    if any(decimal(line["amount_rub"]) < 0 for line in lines) or amount(sum((decimal(line["amount_rub"]) for line in lines), Decimal(0))) != amount(deal.total_price_rub):
        raise HTTPException(409, "Строки сохранённой сметы не совпадают с суммой заказа")
    if any(str(line.get("payee_company_id")) != str(deal.seller_company_id) for line in lines):
        raise HTTPException(409, "Заказ содержит платежи разным получателям. Экспортируйте их отдельно")
    return snapshot, lines


def order_rows(deal):
    snapshot, lines = agreed_lines(deal)
    unit = order_unit(snapshot["need"]["characteristics"])
    name = (snapshot.get("product") or {}).get("name") or snapshot["need"]["category"]
    result = []
    for line in lines:
        goods = line["code"] == "goods"
        result.append({"id": str((snapshot.get("offer") or {}).get("product_id") or deal.need_id) if goods else f"service-{deal.id}-{line['code']}",
            "name": name if goods else line["title"], "quantity": deal.units if goods else 1,
            "unit": unit if goods else "шт", "price": decimal(snapshot["estimate"]["unit_price_rub"]) if goods else decimal(line["amount_rub"]),
            "amount": amount(line["amount_rub"]), "tax_basis": line.get("tax_basis", "unknown"), "vat_rate": line.get("vat_rate_pct"),
            "vat": line.get("included_vat_rub"), "goods": goods})
    return snapshot, result


def _element(parent, name, value=None, **attrs):
    node = ET.SubElement(parent, f"{{{NAMESPACE}}}{name}", attrs)
    if value is not None:
        value = str(value)
        if re.search(r"[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]", value):
            raise HTTPException(422, "Текст содержит недопустимые для XML символы")
        node.text = value
    return node


def commerceml(deal, buyer, seller):
    snapshot, rows = order_rows(deal)
    # CommerceML's СуммаТип allows only two decimal places, including unit price.
    # Never silently round an exact unit price or a distributed group amount.
    for row in rows:
        if row["price"] != amount(row["price"]) or amount(row["price"] * row["quantity"]) != row["amount"]:
            raise HTTPException(409, "CommerceML допускает цену до копейки. Для этой цены или распределённой суммы скачайте точный CSV заказа")
    root = ET.Element(f"{{{NAMESPACE}}}КоммерческаяИнформация", {"ВерсияСхемы": "2.10", "ДатаФормирования": deal.created_at.isoformat()})
    doc = _element(root, "Документ")
    for name, value in [("Ид", deal.id), ("Номер", str(deal.id)), ("Дата", deal.created_at.date().isoformat()),
                        ("ХозОперация", "Заказ товара"), ("Роль", "Продавец"), ("Валюта", "RUB"), ("Курс", "1"), ("Сумма", format(amount(deal.total_price_rub), "f"))]:
        _element(doc, name, value)
    parties = _element(doc, "Контрагенты")
    for company, role in [(buyer, "Покупатель"), (seller, "Продавец")]:
        node = _element(parties, "Контрагент")
        _element(node, "Ид", company["id"])
        _element(node, "Наименование", company["display_name"])
        _element(node, "ПолноеНаименование" if company["legal_form"] == "ИП" else "ОфициальноеНаименование", company["full_name"])
        if company.get("legal_address") and company["legal_form"] != "ИП":
            _element(_element(node, "ЮридическийАдрес"), "Представление", company["legal_address"])
        _element(node, "ИНН", company["inn"])
        if company.get("kpp"):
            _element(node, "КПП", company["kpp"])
        _element(node, "Роль", role)
    _element(doc, "Комментарий", f"Заказ ПоРукам {deal.id}. Не подтверждает оплату. Спецификация: " + json.dumps(snapshot["need"]["characteristics"], ensure_ascii=False, sort_keys=True))
    products = _element(doc, "Товары")
    for row in rows:
        node = _element(products, "Товар")
        _element(node, "Ид", row["id"][:80])
        _element(node, "Наименование", row["name"])
        attrs = {"НаименованиеПолное": row["unit"], "НаименованиеКраткое": row["unit"]}
        if row["unit"] == "шт":
            attrs["Код"] = "796"
        _element(node, "БазоваяЕдиница", row["unit"], **attrs)
        if not row["goods"]:
            requisites = _element(node, "ЗначенияРеквизитов")
            item = _element(requisites, "ЗначениеРеквизита")
            _element(item, "Наименование", "ВидНоменклатуры")
            _element(item, "Значение", "Услуга")
        _element(node, "ЦенаЗаЕдиницу", format(amount(row["price"]), "f"))
        _element(node, "Количество", row["quantity"])
        _element(node, "Сумма", format(row["amount"], "f"))
        if row["tax_basis"] == "includes_vat" and row["vat"] is not None:
            tax = _element(_element(node, "Налоги"), "Налог")
            _element(tax, "Наименование", "НДС")
            _element(tax, "УчтеноВСумме", "true")
            _element(tax, "Сумма", format(amount(row["vat"]), "f"))
            _element(tax, "Ставка", row["vat_rate"])
    requisites = _element(doc, "ЗначенияРеквизитов")
    for key, value in [("Статус заказа", deal.status), ("Проведен", "false"), ("Контракт экспорта", "porukam-1c-1"), ("Срок поставки", snapshot["need"]["deadline_date"]),
                       ("Адрес доставки", json.dumps(snapshot["need"].get("delivery_address"), ensure_ascii=False)), ("Налоговая база", snapshot["estimate"]["terms"]["tax_basis"])]:
        item = _element(requisites, "ЗначениеРеквизита")
        _element(item, "Наименование", key)
        _element(item, "Значение", value)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def order_csv(deal, buyer, seller):
    snapshot, rows = order_rows(deal)
    header = ["Заказ", "Дата", "Покупатель", "ИНН покупателя", "Поставщик", "ИНН поставщика", "Номенклатура", "Количество", "Единица", "Цена", "Сумма", "Валюта", "Срок поставки", "Налоговая база", "Ид номенклатуры", "Характеристики"]
    return csv_bytes([header] + [[str(deal.id), deal.created_at.strftime("%d.%m.%y"), buyer["full_name"], buyer["inn"], seller["full_name"], seller["inn"],
        r["name"], r["quantity"], r["unit"], format(r["price"], "f"), format(r["amount"], "f"), "RUB", date_label(snapshot["need"]["deadline_date"]), r["tax_basis"], r["id"], json.dumps(snapshot["need"]["characteristics"], ensure_ascii=False)] for r in rows])


def date_label(value):
    from datetime import date
    return date.fromisoformat(value).strftime("%d.%m.%y")

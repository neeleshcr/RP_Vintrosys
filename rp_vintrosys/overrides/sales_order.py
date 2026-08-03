import frappe
from frappe.utils import flt, today
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


def apply_pricing_rule(doc, method=None):
    """
    Server-side hook for Sales Order doc_events (before_validate/validate).
    Ensures ERPNext Pricing Rules are resolved and applied to each Sales Order item row.
    """
    if not doc.get("customer") or not doc.get("items"):
        return

    customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")

    for item in doc.get("items"):
        if not item.item_code or item.get("ignore_pricing_rule"):
            continue

        if not flt(item.price_list_rate) and doc.selling_price_list:
            item.price_list_rate = flt(frappe.db.get_value(
                "Item Price",
                {"item_code": item.item_code, "price_list": doc.selling_price_list, "selling": 1},
                "price_list_rate"
            ))

        args = frappe._dict({
            "doctype": doc.doctype or "Sales Order",
            "transaction_type": "selling",
            "company": doc.company,
            "customer": doc.customer,
            "customer_group": customer_group,
            "currency": doc.currency,
            "price_list": doc.selling_price_list,
            "item_code": item.item_code,
            "qty": flt(item.qty) or 1.0,
            "uom": item.uom,
            "stock_uom": item.stock_uom,
            "transaction_date": str(doc.transaction_date or today()),
            "conversion_factor": flt(item.conversion_factor) or 1.0,
            "price_list_rate": flt(item.price_list_rate),
            "rate": flt(item.rate),
            "ignore_pricing_rule": item.get("ignore_pricing_rule", 0),
        })

        rule = get_pricing_rule_for_item(args)

        if rule and rule.get("has_pricing_rule"):
            pricing_rules = rule.get("pricing_rules") or rule.get("pricing_rule")
            if pricing_rules:
                item.pricing_rules = pricing_rules

            discount = flt(rule.get("discount_percentage", 0))
            disc_amt = flt(rule.get("discount_amount", 0))

            if discount > 0:
                item.discount_percentage = discount
                if flt(item.price_list_rate) > 0:
                    precision = item.precision("discount_amount") if hasattr(item, "precision") else 2
                    item.discount_amount = flt(item.price_list_rate * (discount / 100.0), precision)
                    rate_precision = item.precision("rate") if hasattr(item, "precision") else 2
                    item.rate = flt(item.price_list_rate - item.discount_amount, rate_precision)
            elif disc_amt > 0:
                item.discount_amount = disc_amt
                if flt(item.price_list_rate) > 0:
                    item.discount_percentage = flt((disc_amt / item.price_list_rate) * 100.0)
                    rate_precision = item.precision("rate") if hasattr(item, "precision") else 2
                    item.rate = flt(item.price_list_rate - disc_amt, rate_precision)

            amt_precision = item.precision("amount") if hasattr(item, "precision") else 2
            item.amount = flt(flt(item.rate) * flt(item.qty), amt_precision)
        else:
            item.pricing_rules = None
            item.discount_percentage = 0.0
            item.discount_amount = 0.0
            if flt(item.price_list_rate) > 0:
                rate_precision = item.precision("rate") if hasattr(item, "precision") else 2
                item.rate = flt(item.price_list_rate, rate_precision)
            amt_precision = item.precision("amount") if hasattr(item, "precision") else 2
            item.amount = flt(flt(item.rate) * flt(item.qty), amt_precision)

    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()


@frappe.whitelist()
def get_pricing_rule_details(doc):
    """
    Whitelisted endpoint for client-side JS on Sales Order form.
    Receives Sales Order doc (dict or JSON string), applies pricing rules to item rows, and returns updated item details.
    """
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    if isinstance(doc, dict):
        doc_obj = frappe.get_doc(doc)
    else:
        doc_obj = doc

    apply_pricing_rule(doc_obj)

    items_data = []
    for item in doc_obj.items:
        items_data.append({
            "docname": item.name,
            "item_code": item.item_code,
            "pricing_rules": item.pricing_rules,
            "discount_percentage": item.discount_percentage,
            "discount_amount": item.discount_amount,
            "price_list_rate": item.price_list_rate,
            "rate": item.rate,
            "amount": item.amount,
        })
    return items_data
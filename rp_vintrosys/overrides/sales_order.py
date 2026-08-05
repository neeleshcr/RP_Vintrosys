"""
rp_vintrosys/overrides/sales_order.py

Sales Order – Manual Rate Preservation
---------------------------------------
When a user manually edits an item's rate, the JS sets ignore_pricing_rule = 1
on that row. This module ensures that flag is respected on the server side,
preventing ERPNext's validate cycle from overwriting the user-entered rate.
"""

import frappe
from frappe.utils import flt, today
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


def create_custom_fields():
    """Ensure the ignore_pricing_rule Check field exists on Sales Order Item."""
    if not frappe.db.exists("Custom Field", "Sales Order Item-ignore_pricing_rule"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Sales Order Item",
            "fieldname": "ignore_pricing_rule",
            "label": "Ignore Pricing Rule",
            "fieldtype": "Check",
            "default": "0",
            "insert_after": "pricing_rules"
        }).insert(ignore_permissions=True)
        frappe.clear_cache(doctype="Sales Order Item")


class CustomSalesOrder(SalesOrder):
    """
    Overrides apply_pricing_rule_on_items so that rows with
    ignore_pricing_rule == 1 are left untouched by ERPNext's
    internal set_missing_item_details() → apply_pricing_rule_on_items() call.
    """

    def apply_pricing_rule_on_items(self, item, pricing_rule_args):
        if flt(item.get("ignore_pricing_rule")):
            # Keep the user-entered rate; just ensure amount is consistent
            item.pricing_rules = None
            item.discount_percentage = 0.0
            item.discount_amount = 0.0
            item.price_list_rate = flt(item.rate)
            item.amount = flt(item.rate * item.qty, _precision(item, "amount"))
            return
        super().apply_pricing_rule_on_items(item, pricing_rule_args)


# ---------------------------------------------------------------------------
# Doc Event Hook  (before_validate + validate)
# ---------------------------------------------------------------------------

def apply_pricing_rule(doc, method=None):
    """
    Applies pricing rules to Sales Order items.
    Rows with ignore_pricing_rule == 1 are preserved as-is.
    """
    if not doc.get("customer") or not doc.get("items"):
        return

    create_custom_fields()

    customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")

    for item in doc.items:
        if not item.item_code:
            continue

        if flt(item.get("ignore_pricing_rule")):
            # Manual override – keep rate, just sync dependent fields
            item.pricing_rules = None
            item.discount_percentage = 0.0
            item.discount_amount = 0.0
            item.price_list_rate = flt(item.rate)
            item.amount = flt(item.rate * item.qty, _precision(item, "amount"))
            continue

        # Fetch price_list_rate from Item Price if missing
        if not flt(item.price_list_rate) and doc.selling_price_list:
            item.price_list_rate = flt(frappe.db.get_value(
                "Item Price",
                {"item_code": item.item_code, "price_list": doc.selling_price_list, "selling": 1},
                "price_list_rate"
            ))

        args = frappe._dict({
            "doctype": "Sales Order",
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
            "ignore_pricing_rule": 0,
        })

        rule = get_pricing_rule_for_item(args)

        if rule and rule.get("has_pricing_rule"):
            pricing_rules = rule.get("pricing_rules") or rule.get("pricing_rule")
            if pricing_rules:
                item.pricing_rules = pricing_rules

            discount_pct = flt(rule.get("discount_percentage", 0))
            disc_amt     = flt(rule.get("discount_amount", 0))

            if discount_pct > 0:
                item.discount_percentage = discount_pct
                if flt(item.price_list_rate) > 0:
                    item.discount_amount = flt(
                        item.price_list_rate * (discount_pct / 100.0),
                        _precision(item, "discount_amount")
                    )
                    item.rate = flt(
                        item.price_list_rate - item.discount_amount,
                        _precision(item, "rate")
                    )
            elif disc_amt > 0:
                item.discount_amount = disc_amt
                if flt(item.price_list_rate) > 0:
                    item.discount_percentage = flt((disc_amt / item.price_list_rate) * 100.0)
                    item.rate = flt(
                        item.price_list_rate - disc_amt,
                        _precision(item, "rate")
                    )
        else:
            # No rule found via our lookup.
            # If ERPNext's standard flow already set a pricing rule on this row,
            # preserve it — don't wipe the discount.
            if not item.get("pricing_rules"):
                item.pricing_rules = None
                item.discount_percentage = 0.0
                item.discount_amount = 0.0

                plr = flt(item.price_list_rate)
                current_rate = flt(item.rate)
                if plr > 0 and (current_rate == 0 or current_rate == plr):
                    item.rate = flt(plr, _precision(item, "rate"))

        item.amount = flt(item.rate * item.qty, _precision(item, "amount"))

    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()


# ---------------------------------------------------------------------------
# Whitelisted endpoint for JS client
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pricing_rule_details(doc):
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)
    doc_obj = frappe.get_doc(doc) if isinstance(doc, dict) else doc
    apply_pricing_rule(doc_obj)

    return [
        {
            "docname": item.name,
            "item_code": item.item_code,
            "ignore_pricing_rule": flt(item.get("ignore_pricing_rule", 0)),
            "pricing_rules": item.pricing_rules,
            "discount_percentage": item.discount_percentage,
            "discount_amount": item.discount_amount,
            "price_list_rate": item.price_list_rate,
            "rate": item.rate,
            "amount": item.amount,
        }
        for item in doc_obj.items
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _precision(item, fieldname, default=2):
    try:
        return item.precision(fieldname)
    except Exception:
        return default
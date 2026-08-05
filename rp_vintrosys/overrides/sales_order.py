"""
rp_vintrosys/overrides/sales_order.py
──────────────────────────────────────────────────────────────────────────────
Sales Order – Pricing Rule & Rate Override Management
──────────────────────────────────────────────────────────────────────────────
Key fixes & design:
    1. Custom Field setup: Ensures `ignore_pricing_rule` (Check field, default 0)
       exists on `Sales Order Item` doctype and table.
    
    2. DocType Class Override (`CustomSalesOrder`):
       Overrides `apply_pricing_rule_on_items` from `AccountsController` / `SellingController`.
       When `ignore_pricing_rule == 1` for an item row:
         - Bypasses ERPNext's core pricing rule application for that item row.
         - Keeps rate, price_list_rate, amount intact.
         - Clears discount_percentage, discount_amount, pricing_rules.

    3. Server-side Doc Event Hook (`apply_pricing_rule`):
       Protects rows with `ignore_pricing_rule == 1` from being altered by pricing rules.
       For non-ignored rows, applies matching pricing rules or falls back cleanly.
"""

import frappe
from frappe.utils import flt, today
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


def create_custom_fields():
    """Ensure Custom Field `ignore_pricing_rule` exists on `Sales Order Item`."""
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
    Subclass of ERPNext standard SalesOrder doctype controller.
    Used via `override_doctype_class` in hooks.py.
    """

    def apply_pricing_rule_on_items(self, item, pricing_rule_args):
        """
        Core override: Prevent ERPNext's AccountsController.set_missing_item_details()
        from overwriting user-entered manual rates when ignore_pricing_rule is 1.
        """
        if flt(item.get("ignore_pricing_rule")):
            item.pricing_rules = None
            item.discount_percentage = 0.0
            item.discount_amount = 0.0
            item.price_list_rate = flt(item.rate)
            item.amount = flt(flt(item.rate) * flt(item.qty), _precision(item, "amount"))
            return

        return super().apply_pricing_rule_on_items(item, pricing_rule_args)


# ─────────────────────────────────────────────────────────────────────────────
# Server-side hook (before_validate + validate)
# ─────────────────────────────────────────────────────────────────────────────

def apply_pricing_rule(doc, method=None):
    """
    Server-side hook for Sales Order doc_events (before_validate / validate).
    """
    if not doc.get("customer") or not doc.get("items"):
        return

    # Ensure custom fields exist on system
    create_custom_fields()

    customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")

    for item in doc.get("items"):
        if not item.item_code:
            continue

        # ── CASE 1: User has manually overridden this row ─────────────────────
        if flt(item.get("ignore_pricing_rule")):
            item.pricing_rules = None
            item.discount_percentage = 0.0
            item.discount_amount = 0.0
            item.price_list_rate = flt(item.rate)
            _ensure_amount_consistency(item)
            continue

        # ── Fetch price_list_rate if missing ─────────────────────────────────
        if not flt(item.price_list_rate) and doc.selling_price_list:
            item.price_list_rate = flt(
                frappe.db.get_value(
                    "Item Price",
                    {
                        "item_code": item.item_code,
                        "price_list": doc.selling_price_list,
                        "selling": 1,
                    },
                    "price_list_rate",
                )
            )

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
            "ignore_pricing_rule": 0,
        })

        rule = get_pricing_rule_for_item(args)

        if rule and rule.get("has_pricing_rule"):
            # ── CASE 2: Pricing rule found → apply it ─────────────────────────
            pricing_rules = rule.get("pricing_rules") or rule.get("pricing_rule")
            if pricing_rules:
                item.pricing_rules = pricing_rules

            discount_pct = flt(rule.get("discount_percentage", 0))
            disc_amt     = flt(rule.get("discount_amount", 0))

            if discount_pct > 0:
                item.discount_percentage = discount_pct
                if flt(item.price_list_rate) > 0:
                    disc_precision  = _precision(item, "discount_amount")
                    rate_precision  = _precision(item, "rate")
                    item.discount_amount = flt(item.price_list_rate * (discount_pct / 100.0), disc_precision)
                    item.rate            = flt(item.price_list_rate - item.discount_amount, rate_precision)

            elif disc_amt > 0:
                item.discount_amount = disc_amt
                if flt(item.price_list_rate) > 0:
                    item.discount_percentage = flt((disc_amt / item.price_list_rate) * 100.0)
                    rate_precision           = _precision(item, "rate")
                    item.rate                = flt(item.price_list_rate - disc_amt, rate_precision)

            amt_precision  = _precision(item, "amount")
            item.amount    = flt(flt(item.rate) * flt(item.qty), amt_precision)

        else:
            # ── CASE 3: No pricing rule found ─────────────────────────────────
            item.pricing_rules       = None
            item.discount_percentage = 0.0
            item.discount_amount     = 0.0

            plr = flt(item.price_list_rate)
            current_rate = flt(item.rate)

            if plr > 0 and (current_rate == 0 or current_rate == plr):
                rate_precision = _precision(item, "rate")
                item.rate      = flt(plr, rate_precision)

            amt_precision = _precision(item, "amount")
            item.amount   = flt(flt(item.rate) * flt(item.qty), amt_precision)

    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()


# ─────────────────────────────────────────────────────────────────────────────
# Whitelisted endpoint for the JS client
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_pricing_rule_details(doc):
    """
    Client-facing endpoint called by sales_order.js.
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
            "docname":            item.name,
            "item_code":          item.item_code,
            "ignore_pricing_rule": flt(item.get("ignore_pricing_rule", 0)),
            "pricing_rules":      item.pricing_rules,
            "discount_percentage": item.discount_percentage,
            "discount_amount":    item.discount_amount,
            "price_list_rate":    item.price_list_rate,
            "rate":               item.rate,
            "amount":             item.amount,
        })
    return items_data


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _precision(item, fieldname, default=2):
    try:
        return item.precision(fieldname)
    except Exception:
        return default


def _ensure_amount_consistency(item):
    expected_amount = flt(flt(item.rate) * flt(item.qty), _precision(item, "amount"))
    if abs(flt(item.amount) - expected_amount) > 0.001:
        item.amount = expected_amount
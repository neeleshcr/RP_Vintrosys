import frappe
from frappe.utils import cint, flt, today
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item

CUSTOM_FIELDS = [
    {
        "fieldname": "custom_is_rate_overridden",
        "label": "Rate Overridden Manually",
        "fieldtype": "Check",
        "default": "0",
        "read_only": 1,
        "insert_after": "rate",
        "description": "Set to 1 when item rate is manually edited by user.",
    },
    {
        "fieldname": "custom_manual_rate",
        "label": "Manual Rate Override",
        "fieldtype": "Currency",
        "options": "currency",
        "default": "0",
        "read_only": 1,
        "insert_after": "custom_is_rate_overridden",
        "description": "Stores user manually edited item rate.",
    },
    {
        "fieldname": "custom_is_discount_explicit",
        "label": "Discount Overridden Manually",
        "fieldtype": "Check",
        "default": "0",
        "read_only": 1,
        "insert_after": "discount_percentage",
        "description": "Set to 1 when discount percentage is manually edited by user.",
    },
    {
        "fieldname": "custom_explicit_discount",
        "label": "Explicit Discount Override",
        "fieldtype": "Percent",
        "default": "0",
        "read_only": 1,
        "insert_after": "custom_is_discount_explicit",
        "description": "Stores user manually edited discount percentage.",
    },
]


def setup_custom_fields():
    """Idempotently creates the override-tracking fields on Sales Order Item."""
    missing = [
        field for field in CUSTOM_FIELDS
        if not frappe.db.exists("Custom Field", {"dt": "Sales Order Item", "fieldname": field["fieldname"]})
    ]
    if missing:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
        create_custom_fields({"Sales Order Item": missing})


def _precision(item, fieldname, default=2):
    return item.precision(fieldname) if hasattr(item, "precision") else default


def _clear_margin(item):
    """This app always resolves rate/discount itself, so a row never carries a Margin.
    Left uncleared, ERPNext's own calculate_item_rate() stamps margin fields onto a row
    whenever rate > price_list_rate, which then corrupts the next recalculation.
    """
    item.margin_type = None
    item.margin_rate_or_amount = 0.0


def _recalculate_item_totals(item, conversion_rate):
    """Recomputes amount/base_rate/net_rate/etc. from item.rate (set by the caller).

    item.rate/item.qty are run through flt() individually before the multiplication, not just
    the result - a row can still be mid-entry (item_code picked, qty not typed yet) when this
    runs, because apply_pricing_rules() on the client sends the *whole* document on every
    single field edit, so an in-progress row on a different line can ride along as None.
    """
    rate = item.rate = flt(item.rate)
    qty = flt(item.qty)
    item.amount = flt(rate * qty, _precision(item, "amount"))
    item.base_rate = flt(rate * conversion_rate, 2)
    item.base_amount = flt(item.amount * conversion_rate, 2)
    item.net_rate = item.rate
    item.net_amount = item.amount
    item.base_net_rate = item.base_rate
    item.base_net_amount = item.base_amount


def _apply_manual_rate(item, price_list_rate):
    """Precedence 1: a manually typed Rate/Amount wins outright and clears any discount override."""
    item.custom_is_discount_explicit = 0
    item.custom_explicit_discount = 0.0

    item.rate = flt(item.get("custom_manual_rate") or item.rate, _precision(item, "rate"))
    item.pricing_rules = ""

    if price_list_rate <= 0:
        item.discount_amount = 0.0
        item.discount_percentage = 0.0
        return

    discount_amount = flt(price_list_rate - item.rate, _precision(item, "discount_amount"))
    discount_percentage = flt((discount_amount / price_list_rate) * 100.0, _precision(item, "discount_percentage"))

    # Rate at/above price_list_rate is a markup, not a discount - show 0%, not a negative one.
    item.discount_amount = max(discount_amount, 0.0)
    item.discount_percentage = max(discount_percentage, 0.0)


def _apply_manual_discount(item, price_list_rate):
    """Precedence 2: a manually typed Discount % wins next."""
    item.discount_percentage = flt(item.get("custom_explicit_discount"))
    item.pricing_rules = ""

    if price_list_rate <= 0:
        item.discount_amount = 0.0
        return

    item.discount_amount = flt(price_list_rate * (item.discount_percentage / 100.0), _precision(item, "discount_amount"))
    item.rate = flt(price_list_rate - item.discount_amount, _precision(item, "rate"))


def _get_pricing_rule_args(doc, item, customer_group, territory, price_list_rate):
    item_group = item.get("item_group")
    brand = item.get("brand")
    if not (item_group and brand):
        item_info = frappe.db.get_value("Item", item.item_code, ["item_group", "brand"], as_dict=True)
        if item_info:
            item_group = item_group or item_info.item_group
            brand = brand or item_info.brand

    return frappe._dict({
        "doctype": doc.doctype or "Sales Order",
        "transaction_type": "selling",
        "company": doc.company,
        "customer": doc.customer,
        "customer_group": customer_group,
        "territory": territory,
        "currency": doc.currency,
        "price_list": doc.selling_price_list,
        "item_code": item.item_code,
        "item_group": item_group,
        "brand": brand,
        "qty": flt(item.qty) or 1.0,
        "uom": item.uom,
        "stock_uom": item.stock_uom,
        "transaction_date": str(doc.transaction_date or today()),
        "conversion_factor": flt(item.conversion_factor) or 1.0,
        "price_list_rate": price_list_rate,
        "rate": flt(item.rate),
        "ignore_pricing_rule": 0,
    })


def _apply_pricing_rule_or_price_list(doc, item, customer_group, territory, price_list_rate):
    """Precedence 3 & 4: no override on this row - resolve fresh from the Pricing Rule,
    falling back to the plain Price List rate.
    """
    rate_precision = _precision(item, "rate")
    args = _get_pricing_rule_args(doc, item, customer_group, territory, price_list_rate)
    rule = get_pricing_rule_for_item(args)

    if not (rule and rule.get("has_pricing_rule")):
        item.pricing_rules = ""
        item.discount_percentage = 0.0
        item.discount_amount = 0.0
        if price_list_rate > 0:
            item.rate = flt(price_list_rate, rate_precision)
        return

    item.pricing_rules = rule.get("pricing_rules") or rule.get("pricing_rule") or ""
    discount_percentage = flt(rule.get("discount_percentage", 0))

    if discount_percentage > 0 and price_list_rate > 0:
        item.discount_percentage = discount_percentage
        item.discount_amount = flt(price_list_rate * (discount_percentage / 100.0), _precision(item, "discount_amount"))
        item.rate = flt(price_list_rate - item.discount_amount, rate_precision)
    elif flt(rule.get("discount_amount", 0)) > 0:
        item.discount_percentage = 0.0
        item.discount_amount = flt(rule.get("discount_amount"), _precision(item, "discount_amount"))
        if price_list_rate > 0:
            item.rate = flt(price_list_rate - item.discount_amount, rate_precision)
    else:
        item.discount_percentage = 0.0
        item.discount_amount = 0.0
        if price_list_rate > 0:
            item.rate = flt(price_list_rate, rate_precision)


def _resolve_item_pricing(doc, item, customer_group, territory):
    """Resolves Rate/Discount for one row using a single precedence:
    manual rate > manual discount > pricing rule > price list.
    """
    if not flt(item.price_list_rate) and doc.selling_price_list:
        item.price_list_rate = flt(frappe.db.get_value(
            "Item Price",
            {"item_code": item.item_code, "price_list": doc.selling_price_list, "selling": 1},
            "price_list_rate",
        ))

    price_list_rate = flt(item.price_list_rate)
    _clear_margin(item)

    if cint(item.get("custom_is_rate_overridden")):
        _apply_manual_rate(item, price_list_rate)
    elif cint(item.get("custom_is_discount_explicit")):
        _apply_manual_discount(item, price_list_rate)
    else:
        _apply_pricing_rule_or_price_list(doc, item, customer_group, territory, price_list_rate)


def _reassert_manual_rate_overrides(doc, conversion_rate):
    """calculate_taxes_and_totals() should not touch overridden rows (pricing_rules was
    cleared already), but re-assert here too so a save can never silently drop a manual
    rate override.

    For a clamped markup row (rate > price_list_rate, discount shown as 0%), rate =
    price_list_rate - discount_amount no longer holds, so calculate_taxes_and_totals() falls
    through to ERPNext's own margin handling and re-stamps margin_type on the row even though
    rate itself never actually changed. Clear it unconditionally, before the "already correct"
    early-exit below would otherwise skip past it.
    """
    for item in doc.get("items"):
        if not item.item_code or not cint(item.get("custom_is_rate_overridden")):
            continue

        _clear_margin(item)

        rate_precision = _precision(item, "rate")
        target_rate = flt(item.get("custom_manual_rate") or item.rate, rate_precision)
        if flt(item.rate, rate_precision) == target_rate:
            continue

        item.rate = target_rate
        price_list_rate = flt(item.price_list_rate)
        if price_list_rate > 0:
            discount_amount = flt(price_list_rate - item.rate, _precision(item, "discount_amount"))
            discount_percentage = flt((discount_amount / price_list_rate) * 100.0, _precision(item, "discount_percentage"))
            item.discount_amount = max(discount_amount, 0.0)
            item.discount_percentage = max(discount_percentage, 0.0)
        else:
            item.discount_amount = 0.0
            item.discount_percentage = 0.0
        _recalculate_item_totals(item, conversion_rate)


def apply_pricing_rule(doc, method=None):
    """Doc event hook for Sales Order (before_validate/validate).

    Resolves every item row via _resolve_item_pricing() so Rate and Discount % are always
    decided together and stay consistent across Qty/Rate edits, then re-asserts manual rate
    overrides once more after calculate_taxes_and_totals() as a safety net.
    """
    if not doc.get("customer") or not doc.get("items"):
        return

    setup_custom_fields()
    customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")
    territory = frappe.db.get_value("Customer", doc.customer, "territory")
    conversion_rate = flt(getattr(doc, "conversion_rate", 1.0)) or 1.0

    for item in doc.get("items"):
        if not item.item_code or item.get("ignore_pricing_rule"):
            continue
        _resolve_item_pricing(doc, item, customer_group, territory)
        _recalculate_item_totals(item, conversion_rate)

    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()

    _reassert_manual_rate_overrides(doc, conversion_rate)


@frappe.whitelist()
def get_pricing_rule_details(doc):
    """Whitelisted endpoint for the client JS: applies pricing rules to a (possibly unsaved)
    Sales Order and returns the resolved values for each item row.
    """
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    raw_items = doc.get("items") if isinstance(doc, dict) else []
    doc_obj = frappe.get_doc(doc) if isinstance(doc, dict) else doc

    # Preserve custom override fields from the raw payload if frappe.get_doc()'s standard
    # set_missing_values wiped them.
    for idx, item in enumerate(doc_obj.items):
        if idx >= len(raw_items) or not isinstance(raw_items[idx], dict):
            continue
        raw = raw_items[idx]
        if raw.get("custom_is_rate_overridden"):
            item.custom_is_rate_overridden = raw.get("custom_is_rate_overridden")
        if raw.get("custom_manual_rate"):
            item.custom_manual_rate = raw.get("custom_manual_rate")
        elif raw.get("rate") and raw.get("custom_is_rate_overridden"):
            item.custom_manual_rate = raw.get("rate")
        if raw.get("custom_is_discount_explicit"):
            item.custom_is_discount_explicit = raw.get("custom_is_discount_explicit")
        if raw.get("custom_explicit_discount"):
            item.custom_explicit_discount = raw.get("custom_explicit_discount")

    apply_pricing_rule(doc_obj)

    return [
        {
            "docname": item.name,
            "item_code": item.item_code,
            "pricing_rules": item.pricing_rules,
            "discount_percentage": item.discount_percentage,
            "discount_amount": item.discount_amount,
            "price_list_rate": item.price_list_rate,
            "rate": item.rate,
            "amount": item.amount,
            "custom_is_rate_overridden": item.get("custom_is_rate_overridden", 0),
            "custom_is_discount_explicit": item.get("custom_is_discount_explicit", 0),
        }
        for item in doc_obj.items
    ]

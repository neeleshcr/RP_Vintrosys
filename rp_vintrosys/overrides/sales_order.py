import frappe
from frappe.utils import flt, today, cint
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


def setup_custom_fields():
    """
    Ensures custom tracking fields exist on Sales Order Item.
    """
    fields_to_create = []
    if not frappe.db.exists("Custom Field", {"dt": "Sales Order Item", "fieldname": "custom_is_rate_overridden"}):
        fields_to_create.append({
            "fieldname": "custom_is_rate_overridden",
            "label": "Rate Overridden Manually",
            "fieldtype": "Check",
            "default": "0",
            "read_only": 1,
            "insert_after": "rate",
            "description": "Set to 1 when item rate is manually edited by user."
        })
    if not frappe.db.exists("Custom Field", {"dt": "Sales Order Item", "fieldname": "custom_manual_rate"}):
        fields_to_create.append({
            "fieldname": "custom_manual_rate",
            "label": "Manual Rate Override",
            "fieldtype": "Currency",
            "options": "currency",
            "default": "0",
            "read_only": 1,
            "insert_after": "custom_is_rate_overridden",
            "description": "Stores user manually edited item rate."
        })
    if not frappe.db.exists("Custom Field", {"dt": "Sales Order Item", "fieldname": "custom_is_discount_explicit"}):
        fields_to_create.append({
            "fieldname": "custom_is_discount_explicit",
            "label": "Discount Overridden Manually",
            "fieldtype": "Check",
            "default": "0",
            "read_only": 1,
            "insert_after": "discount_percentage",
            "description": "Set to 1 when discount percentage is manually edited by user."
        })
    if not frappe.db.exists("Custom Field", {"dt": "Sales Order Item", "fieldname": "custom_explicit_discount"}):
        fields_to_create.append({
            "fieldname": "custom_explicit_discount",
            "label": "Explicit Discount Override",
            "fieldtype": "Percent",
            "default": "0",
            "read_only": 1,
            "insert_after": "custom_is_discount_explicit",
            "description": "Stores user manually edited discount percentage."
        })

    if fields_to_create:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
        create_custom_fields({"Sales Order Item": fields_to_create})


def apply_pricing_rule(doc, method=None):
    """
    Server-side hook for Sales Order doc_events (before_validate/validate).
    Ensures ERPNext Pricing Rules are resolved for each Sales Order item row,
    and PRESERVES the Pricing Rule discount percentage dynamically across quantity and rate changes.
    """
    if not doc.get("customer") or not doc.get("items"):
        return

    setup_custom_fields()
    customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")
    territory = frappe.db.get_value("Customer", doc.customer, "territory")

    for item in doc.get("items"):
        if not item.item_code or item.get("ignore_pricing_rule"):
            continue

        # Fetch price_list_rate if missing
        if not flt(item.price_list_rate) and doc.selling_price_list:
            item.price_list_rate = flt(frappe.db.get_value(
                "Item Price",
                {"item_code": item.item_code, "price_list": doc.selling_price_list, "selling": 1},
                "price_list_rate"
            ))

        # Get item_group and brand if missing
        item_group = item.get("item_group")
        brand = item.get("brand")
        if not (item_group and brand):
            item_info = frappe.db.get_value("Item", item.item_code, ["item_group", "brand"], as_dict=True)
            if item_info:
                item_group = item_group or item_info.item_group
                brand = brand or item_info.brand

        args = frappe._dict({
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
            "price_list_rate": flt(item.price_list_rate),
            "rate": flt(item.rate),
            "ignore_pricing_rule": item.get("ignore_pricing_rule", 0),
        })

        rule = get_pricing_rule_for_item(args)

        # 1. Determine active Discount Percentage (retain Pricing Rule discount percentage)
        if cint(item.get("custom_is_discount_explicit")) and flt(item.get("custom_explicit_discount")) >= 0:
            effective_discount = flt(item.custom_explicit_discount)
        elif rule and rule.get("has_pricing_rule"):
            effective_discount = flt(rule.get("discount_percentage", 0))
            pricing_rules = rule.get("pricing_rules") or rule.get("pricing_rule")
            if pricing_rules:
                item.pricing_rules = pricing_rules
        else:
            effective_discount = 0.0

        item.discount_percentage = effective_discount

        # 2. Determine Rate and Amount
        if cint(item.get("custom_is_rate_overridden")):
            target_rate = flt(item.get("custom_manual_rate")) or flt(item.rate)
            if target_rate > 0:
                rate_precision = item.precision("rate") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                item.rate = flt(target_rate, rate_precision)
        else:
            if effective_discount > 0 and flt(item.price_list_rate) > 0:
                disc_prec = item.precision("discount_amount") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                item.discount_amount = flt(item.price_list_rate * (effective_discount / 100.0), disc_prec)
                rate_prec = item.precision("rate") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                item.rate = flt(item.price_list_rate - item.discount_amount, rate_prec)
            elif rule and flt(rule.get("discount_amount", 0)) > 0:
                item.discount_amount = flt(rule.get("discount_amount"))
                if flt(item.price_list_rate) > 0:
                    rate_prec = item.precision("rate") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                    item.rate = flt(item.price_list_rate - item.discount_amount, rate_prec)
            else:
                item.discount_amount = 0.0
                if flt(item.price_list_rate) > 0:
                    rate_prec = item.precision("rate") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                    item.rate = flt(item.price_list_rate, rate_prec)

        amt_prec = item.precision("amount") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
        item.amount = flt(flt(item.rate) * flt(item.qty), amt_prec)

        conversion_rate = flt(getattr(doc, "conversion_rate", 1.0)) or 1.0
        item.base_rate = flt(item.rate * conversion_rate, 2)
        item.base_amount = flt(item.amount * conversion_rate, 2)
        item.net_rate = item.rate
        item.net_amount = item.amount
        item.base_net_rate = item.base_rate
        item.base_net_amount = item.base_amount

    if hasattr(doc, "calculate_taxes_and_totals") and callable(getattr(doc, "calculate_taxes_and_totals")):
        doc.calculate_taxes_and_totals()

    # Re-apply manual rate overrides if calculate_taxes_and_totals reset item.rate based on discount_percentage
    for item in doc.get("items"):
        if item.item_code and cint(item.get("custom_is_rate_overridden")):
            target_rate = flt(item.get("custom_manual_rate")) or flt(item.rate)
            if target_rate > 0:
                rate_prec = item.precision("rate") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                amt_prec = item.precision("amount") if hasattr(item, "precision") and callable(getattr(item, "precision")) else 2
                item.rate = flt(target_rate, rate_prec)
                item.amount = flt(flt(item.rate) * flt(item.qty), amt_prec)
                conversion_rate = flt(getattr(doc, "conversion_rate", 1.0)) or 1.0
                item.base_rate = flt(item.rate * conversion_rate, 2)
                item.base_amount = flt(item.amount * conversion_rate, 2)
                item.net_rate = item.rate
                item.net_amount = item.amount
                item.base_net_rate = item.base_rate
                item.base_net_amount = item.base_amount


@frappe.whitelist()
def get_pricing_rule_details(doc):
    """
    Whitelisted endpoint for client-side JS on Sales Order form.
    Receives Sales Order doc (dict or JSON string), applies pricing rules to item rows, and returns updated item details.
    """
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    raw_items = []
    if isinstance(doc, dict) and doc.get("items"):
        raw_items = doc.get("items")

    if isinstance(doc, dict):
        doc_obj = frappe.get_doc(doc)
    else:
        doc_obj = doc

    # Preserve custom override fields from raw payload if standard set_missing_values wiped them
    if raw_items:
        for idx, item in enumerate(doc_obj.items):
            if idx < len(raw_items):
                raw = raw_items[idx]
                if isinstance(raw, dict):
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
            "custom_is_rate_overridden": item.get("custom_is_rate_overridden", 0),
            "custom_is_discount_explicit": item.get("custom_is_discount_explicit", 0),
        })
    return items_data
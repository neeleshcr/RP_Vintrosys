import frappe
from frappe.utils import flt, today
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


def setup_custom_fields():
    """
    Ensures custom_is_rate_overridden and custom_manual_rate fields exist on Sales Order Item.
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
            "description": "Set to 1 when item rate is manually edited by user to prevent pricing rules from overwriting it."
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

    if fields_to_create:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
        create_custom_fields({"Sales Order Item": fields_to_create})


def apply_pricing_rule(doc, method=None):
    """
    Server-side hook for Sales Order doc_events (before_validate/validate).
    Ensures ERPNext Pricing Rules are resolved and applied to each Sales Order item row,
    WHILE preserving manually overridden item rates.
    """
    if not doc.get("customer") or not doc.get("items"):
        return

    setup_custom_fields()
    customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")

    for item in doc.get("items"):
        if not item.item_code or item.get("ignore_pricing_rule"):
            continue

        # If user manually edited the rate, restore custom_manual_rate, set discount_amount/price_list_rate, and recalculate totals
        if item.get("custom_is_rate_overridden"):
            if not item.get("custom_manual_rate") and flt(item.rate) > 0:
                item.custom_manual_rate = flt(item.rate)
            
            target_rate = flt(item.get("custom_manual_rate") or item.rate)
            rate_precision = item.precision("rate") if hasattr(item, "precision") else 2
            item.rate = flt(target_rate, rate_precision)
            item.custom_manual_rate = item.rate

            if flt(item.price_list_rate) > 0 and item.price_list_rate > item.rate:
                disc_prec = item.precision("discount_amount") if hasattr(item, "precision") else 2
                item.discount_amount = flt(item.price_list_rate - item.rate, disc_prec)
                item.discount_percentage = flt((item.discount_amount / item.price_list_rate) * 100.0, 6)
            else:
                item.discount_percentage = 0.0
                item.discount_amount = 0.0
                item.price_list_rate = item.rate

            item.margin_type = None
            item.margin_rate_or_amount = 0.0

            amt_precision = item.precision("amount") if hasattr(item, "precision") else 2
            item.amount = flt(flt(item.rate) * (flt(item.qty) or 1.0), amt_precision)

            conversion_rate = flt(getattr(doc, "conversion_rate", 1.0)) or 1.0
            base_rate_prec = item.precision("base_rate") if hasattr(item, "precision") else 2
            base_amt_prec = item.precision("base_amount") if hasattr(item, "precision") else 2
            item.base_rate = flt(item.rate * conversion_rate, base_rate_prec)
            item.base_amount = flt(item.amount * conversion_rate, base_amt_prec)
            item.net_rate = item.rate
            item.net_amount = item.amount
            item.base_net_rate = item.base_rate
            item.base_net_amount = item.base_amount
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

        conversion_rate = flt(getattr(doc, "conversion_rate", 1.0)) or 1.0
        base_rate_prec = item.precision("base_rate") if hasattr(item, "precision") else 2
        base_amt_prec = item.precision("base_amount") if hasattr(item, "precision") else 2
        item.base_rate = flt(item.rate * conversion_rate, base_rate_prec)
        item.base_amount = flt(item.amount * conversion_rate, base_amt_prec)
        item.net_rate = item.rate
        item.net_amount = item.amount
        item.base_net_rate = item.base_rate
        item.base_net_amount = item.base_amount

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
            "custom_is_rate_overridden": item.get("custom_is_rate_overridden", 0),
        })
    return items_data


def inspect_rp_app():
    import pkgutil, importlib, inspect
    import india_compliance
    for importer, modname, ispkg in pkgutil.walk_packages(india_compliance.__path__, india_compliance.__name__ + "."):
        try:
            mod = importlib.import_module(modname)
            for name, obj in inspect.getmembers(mod, inspect.isfunction):
                src = inspect.getsource(obj)
                if "No GST is being charged on Taxable Items" in src:
                    print("FOUND IN FUNC:", name, "in module:", modname)
                    print(src)
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                for mname, mobj in inspect.getmembers(obj, inspect.isfunction):
                    src = inspect.getsource(mobj)
                    if "No GST is being charged on Taxable Items" in src:
                        print("FOUND IN METHOD:", name, ".", mname, "in module:", modname)
                        print(src)
        except Exception:
            pass
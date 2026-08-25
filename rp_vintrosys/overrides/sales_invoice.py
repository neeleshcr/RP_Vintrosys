import frappe
from india_compliance.gst_india.overrides.transaction import ItemGSTTreatment

# Store original method
_original_set_default_treatment = ItemGSTTreatment.set_default_treatment


def patched_set_default_treatment(self):

    _original_set_default_treatment(self)

    if getattr(self, "doc", None) and self.doc.get("is_consolidated"):
        pos_item_names = [item.pos_invoice_item for item in self.doc.items if item.get("pos_invoice_item")]
        if pos_item_names:
            pos_items = frappe.get_all(
                "POS Invoice Item",
                filters={"name": ["in", pos_item_names]},
                fields=["name", "gst_treatment"],
            )
            treatment_map = {d["name"]: d.get("gst_treatment") for d in pos_items}

            for item in self.doc.items:
                if item.get("pos_invoice_item"):
                    orig_treatment = treatment_map.get(item.pos_invoice_item)
                    if orig_treatment and orig_treatment in ("Nil-Rated", "Exempted", "Non-GST", "Zero-Rated"):
                        item.gst_treatment = orig_treatment


# Apply patch
ItemGSTTreatment.set_default_treatment = patched_set_default_treatment


def fix_consolidated_sales_invoice_gst(doc, method=None):

    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    if not doc.get("is_consolidated"):
        return

    pos_item_names = [item.pos_invoice_item for item in doc.items if item.get("pos_invoice_item")]
    if not pos_item_names:
        return

    pos_items = frappe.get_all(
        "POS Invoice Item",
        filters={"name": ["in", pos_item_names]},
        fields=[
            "name",
            "gst_treatment",
            "taxable_value",
            "cgst_rate",
            "sgst_rate",
            "igst_rate",
            "cess_rate",
            "cess_non_advol_rate",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "cess_amount",
            "cess_non_advol_amount",
            "item_tax_template",
        ],
    )
    pos_item_map = {d["name"]: d for d in pos_items}

    for item in doc.items:
        if not item.get("pos_invoice_item"):
            continue

        source_pos_item = pos_item_map.get(item.pos_invoice_item)
        if not source_pos_item:
            continue

        if source_pos_item.get("gst_treatment"):
            item.gst_treatment = source_pos_item["gst_treatment"]
        if source_pos_item.get("item_tax_template"):
            item.item_tax_template = source_pos_item["item_tax_template"]
        if source_pos_item.get("taxable_value") is not None:
            item.taxable_value = source_pos_item["taxable_value"]
        if source_pos_item.get("cgst_rate") is not None:
            item.cgst_rate = source_pos_item["cgst_rate"]
        if source_pos_item.get("sgst_rate") is not None:
            item.sgst_rate = source_pos_item["sgst_rate"]
        if source_pos_item.get("igst_rate") is not None:
            item.igst_rate = source_pos_item["igst_rate"]
        if source_pos_item.get("cess_rate") is not None:
            item.cess_rate = source_pos_item["cess_rate"]
        if source_pos_item.get("cess_non_advol_rate") is not None:
            item.cess_non_advol_rate = source_pos_item["cess_non_advol_rate"]
        if source_pos_item.get("cgst_amount") is not None:
            item.cgst_amount = source_pos_item["cgst_amount"]
        if source_pos_item.get("sgst_amount") is not None:
            item.sgst_amount = source_pos_item["sgst_amount"]
        if source_pos_item.get("igst_amount") is not None:
            item.igst_amount = source_pos_item["igst_amount"]
        if source_pos_item.get("cess_amount") is not None:
            item.cess_amount = source_pos_item["cess_amount"]
        if source_pos_item.get("cess_non_advol_amount") is not None:
            item.cess_non_advol_amount = source_pos_item["cess_non_advol_amount"]
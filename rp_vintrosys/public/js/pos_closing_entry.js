function sync_closing_amounts(frm) {
    if (frm.doc.payment_reconciliation) {
        let changed = false;
        frm.doc.payment_reconciliation.forEach(row => {
            // Only sync if closing_amount is strictly 0 and expected_amount is not 0
            if (row.closing_amount === 0 && row.expected_amount !== 0) {
                row.closing_amount = row.expected_amount || 0;
                row.difference = (row.closing_amount || 0) - (row.expected_amount || 0);
                changed = true;
            }
        });
        if (changed) {
            frm.refresh_field("payment_reconciliation");
        }
    }
}

frappe.ui.form.on("POS Closing Entry", {
    refresh: function (frm) {
        if (frm.doc.docstatus === 0) {
            sync_closing_amounts(frm);
        }
    },
    get_invoices: function (frm) {
        frappe.after_ajax(() => {
            sync_closing_amounts(frm);
        });
    }
});
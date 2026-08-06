frappe.ui.form.on('Sales Order', {
	customer: function(frm) {
		if (frm.doc.customer) {
			frappe.after_ajax(() => {
				setTimeout(() => {
					apply_custom_pricing_rules(frm);
				}, 400);
			});
		}
	},
	selling_price_list: function(frm) {
		if (frm.doc.customer) {
			frappe.after_ajax(() => {
				setTimeout(() => {
					apply_custom_pricing_rules(frm);
				}, 400);
			});
		}
	}
});

frappe.ui.form.on('Sales Order Item', {
	rate: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row && row.item_code) {
			// Mark row as manually overridden and store custom_manual_rate when user edits rate
			frappe.model.set_value(cdt, cdn, 'custom_is_rate_overridden', 1);
			frappe.model.set_value(cdt, cdn, 'custom_manual_rate', row.rate);
		}
	},
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row) {
			// Reset override flag and manual rate when item code changes
			frappe.model.set_value(cdt, cdn, 'custom_is_rate_overridden', 0);
			frappe.model.set_value(cdt, cdn, 'custom_manual_rate', 0);
		}
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	},
	qty: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row && row.custom_is_rate_overridden) {
			let amt = flt(row.rate) * flt(row.qty);
			frappe.model.set_value(cdt, cdn, 'amount', amt);
		}
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	},
	uom: function(frm, cdt, cdn) {
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	}
});

function apply_custom_pricing_rules(frm) {
	if (!frm.doc.customer || !frm.doc.items || !frm.doc.items.length) return;

	frappe.call({
		method: 'rp_vintrosys.overrides.sales_order.get_pricing_rule_details',
		args: {
			doc: frm.doc
		},
		callback: function(r) {
			if (r.message && Array.isArray(r.message)) {
				r.message.forEach((item_data, idx) => {
					let row = frm.doc.items[idx];
					if (row && item_data) {
						if (row.custom_is_rate_overridden) {
							// Preserve manual rate override
							return;
						}
						row.pricing_rules = item_data.pricing_rules || '';
						if (item_data.price_list_rate !== undefined) {
							row.price_list_rate = item_data.price_list_rate;
						}
						if (item_data.discount_percentage !== undefined) {
							row.discount_percentage = item_data.discount_percentage;
						}
						if (item_data.discount_amount !== undefined) {
							row.discount_amount = item_data.discount_amount;
						}
						if (item_data.rate !== undefined) {
							row.rate = item_data.rate;
						}
						if (item_data.amount !== undefined) {
							row.amount = item_data.amount;
						}
					}
				});
				frm.refresh_field('items');
			}
		}
	});
}
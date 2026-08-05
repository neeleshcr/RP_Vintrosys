frappe.ui.form.on('Sales Order', {
	customer: function(frm) {
		if (frm.doc.customer) {
			frappe.after_ajax(() => {
				setTimeout(() => apply_custom_pricing_rules(frm), 400);
			});
		}
	},

	selling_price_list: function(frm) {
		if (frm.doc.customer) {
			frappe.after_ajax(() => {
				setTimeout(() => apply_custom_pricing_rules(frm), 400);
			});
		}
	}
});

frappe.ui.form.on('Sales Order Item', {
	item_code: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		row.ignore_pricing_rule = 0;
		frappe.after_ajax(() => {
			setTimeout(() => apply_custom_pricing_rules(frm), 300);
		});
	},

	qty: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (cint(row.ignore_pricing_rule)) {
			row.amount = flt(row.rate * flt(row.qty), precision('amount', row));
			frm.refresh_field('items');
			frm.trigger('calculate_taxes_and_totals');
		} else {
			frappe.after_ajax(() => {
				setTimeout(() => apply_custom_pricing_rules(frm), 300);
			});
		}
	},

	uom: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (cint(row.ignore_pricing_rule)) {
			row.amount = flt(row.rate * flt(row.qty), precision('amount', row));
			frm.refresh_field('items');
			frm.trigger('calculate_taxes_and_totals');
		} else {
			frappe.after_ajax(() => {
				setTimeout(() => apply_custom_pricing_rules(frm), 300);
			});
		}
	},

	rate: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		row.ignore_pricing_rule = 1;
		row.price_list_rate = flt(row.rate);
		row.discount_percentage = 0;
		row.discount_amount = 0;
		row.pricing_rules = null;
		row.amount = flt(row.rate * flt(row.qty), precision('amount', row));
		frm.refresh_field('items');
		frm.trigger('calculate_taxes_and_totals');
	},

	ignore_pricing_rule: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (!cint(row.ignore_pricing_rule)) {
			apply_custom_pricing_rules(frm);
		}
	}
});

function apply_custom_pricing_rules(frm) {
	if (!frm.doc.customer || !frm.doc.items || !frm.doc.items.length) return;

	frappe.call({
		method: 'rp_vintrosys.overrides.sales_order.get_pricing_rule_details',
		args: { doc: frm.doc },
		callback: function(r) {
			if (r.message && Array.isArray(r.message)) {
				r.message.forEach((item_data, idx) => {
					let row = frm.doc.items[idx];
					if (!row || !item_data || cint(row.ignore_pricing_rule)) return;

					row.pricing_rules       = item_data.pricing_rules || '';
					row.price_list_rate     = item_data.price_list_rate;
					row.discount_percentage = item_data.discount_percentage;
					row.discount_amount     = item_data.discount_amount;
					row.rate                = item_data.rate;
					row.amount              = item_data.amount;
				});
				frm.refresh_field('items');
			}
		}
	});
}

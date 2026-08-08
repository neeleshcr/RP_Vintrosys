let _rp_setting_pricing = false;

frappe.ui.form.on('Sales Order', {
	customer: function(frm) {
		if (frm.doc.customer) {
			_rp_setting_pricing = true;
			frappe.after_ajax(() => {
				setTimeout(() => {
					apply_custom_pricing_rules(frm);
				}, 400);
			});
		}
	},
	selling_price_list: function(frm) {
		if (frm.doc.customer) {
			_rp_setting_pricing = true;
			frappe.after_ajax(() => {
				setTimeout(() => {
					apply_custom_pricing_rules(frm);
				}, 400);
			});
		}
	}
});

frappe.ui.form.on('Sales Order Item', {
	item_code: function(frm, cdt, cdn) {
		_rp_setting_pricing = true;
		let row = locals[cdt][cdn];
		if (row) {
			row.custom_is_rate_overridden = 0;
			row.custom_manual_rate = 0;
			row.custom_is_discount_explicit = 0;
			row.custom_explicit_discount = 0;
		}
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	},

	qty: function(frm, cdt, cdn) {
		_rp_setting_pricing = true;
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	},

	uom: function(frm, cdt, cdn) {
		_rp_setting_pricing = true;
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	},

	rate: function(frm, cdt, cdn) {
		if (_rp_setting_pricing) return;
		let row = locals[cdt][cdn];
		if (!row || !row.item_code) return;

		row.custom_is_rate_overridden = 1;
		row.custom_manual_rate = flt(row.rate);
	},

	amount: function(frm, cdt, cdn) {
		if (_rp_setting_pricing) return;
		let row = locals[cdt][cdn];
		if (!row || !row.item_code || !flt(row.qty)) return;

		let calc_rate = flt(row.amount) / flt(row.qty);
		row.custom_is_rate_overridden = 1;
		row.custom_manual_rate = flt(calc_rate);
	},

	discount_percentage: function(frm, cdt, cdn) {
		if (_rp_setting_pricing) return;
		let row = locals[cdt][cdn];
		if (!row || !row.item_code) return;

		row.custom_is_discount_explicit = 1;
		row.custom_explicit_discount = flt(row.discount_percentage);

		_rp_setting_pricing = true;
		frappe.after_ajax(() => {
			setTimeout(() => {
				apply_custom_pricing_rules(frm);
			}, 300);
		});
	}
});

function apply_custom_pricing_rules(frm) {
	if (!frm.doc.customer || !frm.doc.items || !frm.doc.items.length) {
		_rp_setting_pricing = false;
		return;
	}

	frappe.call({
		method: 'rp_vintrosys.overrides.sales_order.get_pricing_rule_details',
		args: {
			doc: frm.doc
		},
		callback: function(r) {
			if (r.message && Array.isArray(r.message)) {
				_rp_setting_pricing = true;
				try {
					r.message.forEach((item_data, idx) => {
						let row = frm.doc.items[idx];
						if (row && item_data) {
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
							if (item_data.custom_is_rate_overridden !== undefined) {
								row.custom_is_rate_overridden = item_data.custom_is_rate_overridden;
							}
							if (item_data.custom_is_discount_explicit !== undefined) {
								row.custom_is_discount_explicit = item_data.custom_is_discount_explicit;
							}
						}
					});
					frm.refresh_field('items');
				} finally {
					setTimeout(() => {
						_rp_setting_pricing = false;
					}, 600);
				}
			} else {
				_rp_setting_pricing = false;
			}
		},
		error: function() {
			_rp_setting_pricing = false;
		}
	});
}
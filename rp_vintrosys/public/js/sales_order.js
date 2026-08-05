// ─────────────────────────────────────────────────────────────────────────────
// Sales Order – Custom Pricing Rule + Manual Rate Override
// ─────────────────────────────────────────────────────────────────────────────

/** Return true if this item row has been manually overridden. */
function is_manual_rate(row) {
	return cint(row.ignore_pricing_rule) === 1;
}

/** Apply a yellow-tinted CSS badge to the rate cell of a manually-edited row. */
function mark_row_manual(frm, row) {
	let grid_row = frm.fields_dict.items.grid.get_row(row.name);
	if (!grid_row) return;
	let $rate_cell = $(grid_row.row).find('[data-fieldname="rate"]');
	if (!$rate_cell.find('.manual-rate-badge').length) {
		$rate_cell.css('position', 'relative');
		$rate_cell.append(
			`<span class="manual-rate-badge" title="Rate manually set – pricing rule bypassed"
				style="
					position:absolute; top:2px; right:4px;
					background:#fff3cd; color:#856404;
					border:1px solid #ffc107; border-radius:3px;
					font-size:9px; padding:1px 4px; line-height:1.4;
					pointer-events:none; z-index:10;">
				Manual
			</span>`
		);
	}
}

/** Remove the yellow badge from a row that has been reset. */
function unmark_row_manual(frm, row) {
	let grid_row = frm.fields_dict.items.grid.get_row(row.name);
	if (!grid_row) return;
	$(grid_row.row).find('.manual-rate-badge').remove();
	$(grid_row.row).find('[data-fieldname="rate"]').css('position', '');
}

/** Re-render badges for all rows (called on form refresh). */
function refresh_manual_badges(frm) {
	(frm.doc.items || []).forEach(function(row) {
		if (is_manual_rate(row)) {
			mark_row_manual(frm, row);
		} else {
			unmark_row_manual(frm, row);
		}
	});
}

/** Recalculate amount for a manually overridden row locally. */
function recalculate_row(frm, row) {
	let qty  = flt(row.qty) || 1;
	let rate = flt(row.rate);

	row.price_list_rate = rate;
	row.discount_percentage = 0;
	row.discount_amount = 0;
	row.pricing_rules = null;
	row.amount = flt(rate * qty, precision('amount', row));

	frm.refresh_field('items');
	frm.trigger('calculate_taxes_and_totals');
}

/* ─── Main Sales Order events ───────────────────────────────────────────────── */

frappe.ui.form.on('Sales Order', {
	refresh: function(frm) {
		refresh_manual_badges(frm);
		add_reset_pricing_rule_button(frm);
	},

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

/* ─── Sales Order Item events ───────────────────────────────────────────────── */

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

		if (is_manual_rate(row)) {
			recalculate_row(frm, row);
		} else {
			frappe.after_ajax(() => {
				setTimeout(() => apply_custom_pricing_rules(frm), 300);
			});
		}
	},

	uom: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);

		if (is_manual_rate(row)) {
			recalculate_row(frm, row);
		} else {
			frappe.after_ajax(() => {
				setTimeout(() => apply_custom_pricing_rules(frm), 300);
			});
		}
	},

	rate: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);

		row.ignore_pricing_rule = 1;
		recalculate_row(frm, row);
		mark_row_manual(frm, row);

		frappe.show_alert({
			message: __('Rate manually set. Pricing rule bypassed for this row. Use "Reset to Pricing Rule" to revert.'),
			indicator: 'orange'
		}, 4);
	},

	ignore_pricing_rule: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (!cint(row.ignore_pricing_rule)) {
			unmark_row_manual(frm, row);
			apply_custom_pricing_rules(frm);
		}
	}
});

/* ─── Core: apply pricing rules (server call) ───────────────────────────────── */

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
					if (!row || !item_data) return;

					if (is_manual_rate(row)) return;

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
				});

				frm.refresh_field('items');
				setTimeout(() => refresh_manual_badges(frm), 100);
			}
		}
	});
}

/* ─── "Reset to Pricing Rule" button ────────────────────────────────────────── */

function add_reset_pricing_rule_button(frm) {
	frm.add_custom_button(__('Reset to Pricing Rule'), function() {
		let has_manual = false;

		(frm.doc.items || []).forEach(function(row) {
			if (is_manual_rate(row)) {
				has_manual = true;
				row.ignore_pricing_rule = 0;
				unmark_row_manual(frm, row);
			}
		});

		if (!has_manual) {
			frappe.msgprint(__('No rows have a manually overridden rate.'));
			return;
		}

		frappe.show_alert({ message: __('Manual rate overrides cleared. Re-applying pricing rules…'), indicator: 'blue' }, 4);
		apply_custom_pricing_rules(frm);

	}, __('Tools'));
}

let is_applying_pricing_rules = false;
let pricing_request_sequence = 0; 

frappe.ui.form.on('Sales Order', {
	setup: take_over_native_qty_handler,
	customer: recompute_after_native_flow,
	selling_price_list: recompute_after_native_flow,
});

frappe.ui.form.on('Sales Order Item', {
	item_code: on_item_code_change,
	qty: on_qty_change,
	uom: on_uom_change,
	rate: on_rate_change,
	amount: on_amount_change,
	discount_percentage: on_discount_percentage_change,
});


function take_over_native_qty_handler(frm) {
	if (!frm.cscript) return;
	frm.cscript.qty = function (doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (!row) return;
		row.amount = flt(flt(row.rate) * flt(row.qty), precision('amount', row));
		frm.refresh_field('items');
		apply_pricing_rules(frm);
	};
}

function recompute_after_native_flow(frm) {
	if (!frm.doc.customer) return;
	frappe.after_ajax(() => setTimeout(() => apply_pricing_rules(frm), 400));
}

function on_item_code_change(frm, cdt, cdn) {
	reset_row_override(locals[cdt][cdn]);
	frappe.after_ajax(() => setTimeout(() => apply_pricing_rules(frm), 300));
}

function on_qty_change(frm) {
	if (!is_applying_pricing_rules) apply_pricing_rules(frm);
}

function on_uom_change(frm) {
	if (is_applying_pricing_rules) return;
	frappe.after_ajax(() => setTimeout(() => apply_pricing_rules(frm), 300));
}

function on_rate_change(frm, cdt, cdn) {
	if (is_applying_pricing_rules) return;
	let row = locals[cdt][cdn];
	if (!row || !row.item_code) return;
	set_rate_override(row, flt(row.rate));
	apply_pricing_rules(frm);
}

function on_amount_change(frm, cdt, cdn) {
	if (is_applying_pricing_rules) return;
	let row = locals[cdt][cdn];
	if (!row || !row.item_code || !flt(row.qty)) return;
	set_rate_override(row, flt(row.amount) / flt(row.qty));
	apply_pricing_rules(frm);
}

function on_discount_percentage_change(frm, cdt, cdn) {
	if (is_applying_pricing_rules) return;
	let row = locals[cdt][cdn];
	if (!row || !row.item_code) return;
	set_discount_override(row, flt(row.discount_percentage));
	apply_pricing_rules(frm);
}

// A manual Rate/Amount and a manual Discount % are mutually exclusive - setting one always
// clears the other so the two can never disagree about which value is authoritative.
function set_rate_override(row, rate) {
	row.custom_is_rate_overridden = 1;
	row.custom_manual_rate = rate;
	row.custom_is_discount_explicit = 0;
	row.custom_explicit_discount = 0;
}

function set_discount_override(row, discount_percentage) {
	row.custom_is_discount_explicit = 1;
	row.custom_explicit_discount = discount_percentage;
	row.custom_is_rate_overridden = 0;
	row.custom_manual_rate = 0;
}

function reset_row_override(row) {
	if (!row) return;
	row.custom_is_rate_overridden = 0;
	row.custom_manual_rate = 0;
	row.custom_is_discount_explicit = 0;
	row.custom_explicit_discount = 0;
}

function apply_pricing_rules(frm) {
	if (!frm.doc.customer || !frm.doc.items || !frm.doc.items.length) return;

	const request_id = ++pricing_request_sequence;
	is_applying_pricing_rules = true;

	frappe.call({
		method: 'rp_vintrosys.overrides.sales_order.get_pricing_rule_details',
		args: { doc: frm.doc },
		callback(r) {
			if (request_id !== pricing_request_sequence) return; // a newer edit already superseded this
			apply_server_response(frm, r.message);
		},
		error() {
			if (request_id === pricing_request_sequence) is_applying_pricing_rules = false;
		},
	});
}

const SERVER_RESPONSE_FIELDS = [
	'price_list_rate', 'discount_percentage', 'discount_amount',
	'rate', 'amount', 'custom_is_rate_overridden', 'custom_is_discount_explicit',
];

function apply_server_response(frm, items_data) {
	if (!Array.isArray(items_data)) {
		is_applying_pricing_rules = false;
		return;
	}
	try {
		items_data.forEach((item_data, idx) => update_row_from_server(frm.doc.items[idx], item_data));
		frm.refresh_field('items');
		frm.trigger('calculate_taxes_and_totals');
	} finally {
		is_applying_pricing_rules = false;
	}
}

function update_row_from_server(row, item_data) {
	if (!row || !item_data) return;
	row.pricing_rules = item_data.pricing_rules || '';
	for (const field of SERVER_RESPONSE_FIELDS) {
		if (item_data[field] !== undefined) row[field] = item_data[field];
	}
}

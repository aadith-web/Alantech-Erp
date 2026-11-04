// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sub Assembly", {
	refresh(frm) {
		// the Section column of components is only used inside a Technical Offer
		frm.fields_dict.components.grid.update_docfield_property("section", "hidden", 1);
		frm.fields_dict.components.grid.update_docfield_property("section", "in_list_view", 0);
		frm.refresh_field("components");
	},
});

function alt_sub_assembly_totals(frm) {
	let items = 0;
	let expenses = 0;
	(frm.doc.items || []).forEach((row) => {
		row.amount = flt(row.qty) * flt(row.unit_cost);
		items += row.amount * (1 + flt(row.addon_pct) / 100);
	});
	(frm.doc.expenses || []).forEach((row) => {
		row.amount = flt(row.qty) * flt(row.rate);
		expenses += row.amount;
	});
	frm.doc.item_cost = items;
	frm.doc.expense_cost = expenses;
	frm.doc.total_cost = items + expenses;
	frm.refresh_fields();
}

frappe.ui.form.on("Sub Assembly Item", {
	items_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		row.addon_pct = frm.doc.cost_type === "Manpower" ? 0 : 2;
		frm.refresh_field("items");
	},
	items_remove: alt_sub_assembly_totals,
	qty: alt_sub_assembly_totals,
	unit_cost: alt_sub_assembly_totals,
	addon_pct: alt_sub_assembly_totals,
});

frappe.ui.form.on("Sub Assembly Expense", {
	expenses_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!flt(row.qty)) row.qty = 1;
		frm.refresh_field("expenses");
	},
	expenses_remove: alt_sub_assembly_totals,
	qty: alt_sub_assembly_totals,
	rate: alt_sub_assembly_totals,
});

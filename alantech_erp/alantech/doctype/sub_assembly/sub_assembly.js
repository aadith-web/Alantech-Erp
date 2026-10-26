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

frappe.ui.form.on("Sub Assembly Item", {
	items_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		row.addon_pct = frm.doc.cost_type === "Manpower" ? 0 : 2;
		frm.refresh_field("items");
	},
});

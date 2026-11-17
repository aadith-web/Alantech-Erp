// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Notice Period", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Employee"), () => frappe.set_route("Form", "Employee", frm.doc.employee));
		}
	},
});

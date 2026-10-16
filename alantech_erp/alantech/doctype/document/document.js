// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Document", {
	setup(frm) {
		// Only these record types can have documents; edit the list as needed
		const ALLOWED = ["Employee", "Supplier", "Customer", "Company"];
		frm.set_query("reference_doctype", () => ({ filters: { name: ["in", ALLOWED] } }));
		frm.set_query("document_type", () => ({ filters: { disabled: 0 } }));
	},

	onload(frm) {
		if (frm.is_new() && frm.doc.reference_doctype === "Employee" && !frm.doc.reference_name) {
			frappe.db.get_value("Employee", { user_id: frappe.session.user }, "name").then((r) => {
				const employee = r.message && r.message.name;
				if (employee && !frm.doc.reference_name) frm.set_value("reference_name", employee);
			});
		}
	},

	refresh(frm) {
		frm.toggle_enable("reference_doctype", frm.is_new() && !frappe.route_options?.reference_doctype);
		alt_doc.set_card_number_label(frm);
		alt_doc.take_snapshot(frm);
		alt_doc.show_status_intro(frm);
		alt_doc.add_review_buttons(frm);
	},

	document_type(frm) {
		alt_doc.set_card_number_label(frm);
	},

	reference_doctype(frm) {
		if (frm.doc.reference_name) frm.set_value("reference_name", "");
	},

	validate(frm) {
		if (!frm.is_new() && alt_doc.snapshot_of(frm) === frm.__alt_doc_snapshot) {
			frappe.throw({ title: __("Nothing to save"), message: __("No changes to save."), indicator: "orange" });
		}
	},
});

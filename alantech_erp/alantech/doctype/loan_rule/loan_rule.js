// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Rule", {
	setup(frm) {
		const by_company = () => ({ filters: { company: frm.doc.company } });
		frm.set_query("departments", by_company);
		frm.set_query("loan_products", by_company);
	},
});

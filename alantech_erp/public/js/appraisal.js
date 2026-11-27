// Appraisal: "Create Promotion" on a submitted appraisal (ClickUp 14yr2e58nc7,
// setup/appraisal_promotion.py). Opens a new Employee Promotion with the employee, company and
// department filled in; HR completes and saves it. Hidden for Draft / Cancelled appraisals and for
// users who cannot create a promotion.
frappe.ui.form.on("Appraisal", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.model.can_create("Employee Promotion")) return;
		frm.add_custom_button(
			__("Create Promotion"),
			() =>
				frappe.model.open_mapped_doc({
					method: "alantech_erp.setup.appraisal_promotion.make_promotion",
					frm,
				}),
			__("Create")
		);
	},
});

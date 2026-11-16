// Loan form: Lending adds Create > Loan Disbursement for every user; only the Accounts Department
// Head (Accounts Manager) may disburse (setup/loan_permissions.py), so others do not see it.
// Loaded through doctype_js in hooks.py, after Lending's own form script.
frappe.ui.form.on("Loan", {
	refresh(frm) {
		if (frappe.model.can_create("Loan Disbursement")) return;
		frm.remove_custom_button(__("Loan Disbursement"), __("Create"));
	},
});

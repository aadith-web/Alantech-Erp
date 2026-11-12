// Lending forms: show the employee's name under the Applicant box (e.g. "Jincy Jose"), so the
// applicant can be verified without opening the Employee record (Accounts / Loan users usually
// cannot read Employee). Name from alantech_erp.loan_rules.loan.get_applicant_name.
(() => {
	const DOCTYPES = [
		"Collection Case",
		"Loan",
		"Loan Application",
		"Loan Balance Adjustment",
		"Loan Demand",
		"Loan Disbursement",
		"Loan Interest Accrual",
		"Loan Refund",
		"Loan Repayment",
		"Loan Restructure",
		"Loan Security Assignment",
		"Loan Security Release",
		"Loan Security Shortfall",
		"Loan Write Off",
		"Sanctioned Loan Amount",
	];
	const cache = {};

	function show_name(frm, name) {
		const field = frm.get_field("applicant");
		if (!field) return;
		const text = name ? frappe.utils.escape_html(name) : "";
		frm.set_df_property("applicant", "description", text ? `<b>${text}</b>` : "");
	}

	function refresh_name(frm) {
		const { applicant, applicant_type } = frm.doc;
		if (!applicant || (applicant_type && applicant_type !== "Employee")) {
			show_name(frm, null);
			return;
		}
		if (frm.doc.applicant_name) cache[applicant] = frm.doc.applicant_name;
		if (cache[applicant]) {
			show_name(frm, cache[applicant]);
			return;
		}
		frappe
			.xcall("alantech_erp.loan_rules.loan.get_applicant_name", {
				doctype: frm.doctype,
				applicant,
			})
			.then((name) => {
				if (name) cache[applicant] = name;
				if (frm.doc.applicant === applicant) show_name(frm, name);
			});
	}

	const handlers = {
		refresh: refresh_name,
		applicant: refresh_name,
		applicant_type: refresh_name,
	};
	DOCTYPES.forEach((doctype) => frappe.ui.form.on(doctype, handlers));
})();

// Loan Eligibility (LR-08): Loan Rule and eligibility per active employee.
frappe.query_reports["Loan Eligibility"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
			on_change: () => alt_default_loan_product(true),
		},
		{
			// required: Loan Rules are usually limited to products, so a blank product would match
			// no rule for anyone
			fieldname: "loan_product",
			label: __("Loan Product"),
			fieldtype: "Link",
			options: "Loan Product",
			reqd: 1,
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{
			fieldname: "as_on_date",
			label: __("As On Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
	],
	onload() {
		alt_default_loan_product(false);
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "eligible" && data) {
			const color = data.eligible === "Yes" ? "green" : "red";
			value = `<span class="indicator-pill ${color}">${value}</span>`;
		}
		return value;
	},
};

// Fill Loan Product when the company has exactly one; on a company change, clear a product of
// another company first.
function alt_default_loan_product(company_changed) {
	const report = frappe.query_report;
	const company = report.get_filter_value("company");
	if (!company) return;
	if (!company_changed && report.get_filter_value("loan_product")) return;
	frappe.db
		.get_list("Loan Product", { filters: { company }, fields: ["name"], limit: 2 })
		.then((rows) => {
			const current = report.get_filter_value("loan_product");
			if (rows.length === 1) {
				if (current !== rows[0].name) report.set_filter_value("loan_product", rows[0].name);
				return;
			}
			if (!current) return;
			frappe.db.get_value("Loan Product", current, "company").then((r) => {
				if ((r.message || {}).company !== company) report.set_filter_value("loan_product", "");
			});
		});
}

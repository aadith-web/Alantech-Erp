// Commission Statement: commission credits per Sales Person, paid / unpaid.
frappe.query_reports["Commission Statement"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "Sales Person" },
		{
			fieldname: "basis",
			label: __("Basis"),
			fieldtype: "Select",
			options: ["", "Sales Order", "Sales Invoice", "Payment Received"],
		},
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["", "Paid", "Unpaid"] },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "base_amount" && data && data.base_amount < 0) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
};

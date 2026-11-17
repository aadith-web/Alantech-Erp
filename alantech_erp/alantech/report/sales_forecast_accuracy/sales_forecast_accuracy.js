// Sales Forecast Accuracy: submitted forecasts against what was actually won.
frappe.query_reports["Sales Forecast Accuracy"] = {
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
			label: __("Periods From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -6),
			reqd: 1,
		},
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "sales_person", label: __("Sales Person (Team)"), fieldtype: "Link", options: "Sales Person" },
		{ fieldname: "show_team_rows", label: __("Show Team Rows"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "accuracy" && data) {
			const cls = data.accuracy >= 90 ? "text-success" : data.accuracy >= 70 ? "text-warning" : "text-danger";
			value = `<span class="${cls}">${value}</span>`;
		}
		return value;
	},
};

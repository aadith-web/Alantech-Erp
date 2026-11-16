// Sales Forecast: target, closed won and Deals by forecast category, rolled up the Sales Person tree.
frappe.query_reports["Sales Forecast"] = {
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
			fieldname: "period_type",
			label: __("Period"),
			fieldtype: "Select",
			options: ["Month", "Quarter"],
			default: "Month",
			reqd: 1,
		},
		{
			fieldname: "period_start",
			label: __("Period Of"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person (Team)"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{ fieldname: "hide_empty", label: __("Hide Empty Rows"), fieldtype: "Check", default: 1 },
	],
	tree: true,
	name_field: "name",
	parent_field: "parent",
	initial_depth: 2,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "sales_person" && data.is_group) value = `<b>${value}</b>`;
		if (column.fieldname === "gap" && flt(data.gap) > 0) value = `<span class="text-danger">${value}</span>`;
		if (column.fieldname === "achievement_pct" && data.target) {
			const cls = data.achievement_pct >= 100 ? "text-success" : data.achievement_pct >= 70 ? "text-warning" : "text-danger";
			value = `<span class="${cls}">${value}</span>`;
		}
		if (["closed_won", "commit_amount", "best_case", "pipeline", "weighted_pipeline"].includes(column.fieldname) && flt(data[column.fieldname])) {
			value = `<a class="alt-forecast-drill" data-sp="${encodeURIComponent(data.name)}" data-col="${column.fieldname}"
				data-from="${data.from_date}" data-to="${data.to_date}">${value}</a>`;
		}
		return value;
	},

	onload(report) {
		$(report.page.wrapper).on("click", ".alt-forecast-drill", function (e) {
			e.preventDefault();
			const $a = $(this);
			frappe
				.call("alantech_erp.alantech.report.sales_forecast.sales_forecast.drill_down", {
					company: report.get_filter_value("company"),
					sales_person: decodeURIComponent($a.data("sp")),
					column: $a.data("col"),
					from_date: $a.data("from"),
					to_date: $a.data("to"),
				})
				.then((r) => {
					frappe.route_options = r.message.filters;
					frappe.set_route("List", r.message.doctype);
				});
		});
	},
};

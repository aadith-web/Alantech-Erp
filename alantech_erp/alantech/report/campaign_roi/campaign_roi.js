// Campaign ROI (CRM C36): cost, results and return of each campaign; child campaigns under their parent.
frappe.query_reports["Campaign ROI"] = {
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
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "campaign",
			label: __("Campaign"),
			fieldtype: "Link",
			options: "Campaign",
			description: __("That campaign and its child campaigns"),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Planned", "Active", "Completed", "Cancelled"],
		},
		{
			fieldname: "campaign_type",
			label: __("Campaign Type"),
			fieldtype: "Select",
			options: [
				"",
				"Exhibition / Trade Show",
				"Seminar / Event",
				"Email",
				"Social Media",
				"Website / SEO",
				"Advertisement",
				"Referral",
				"Telemarketing",
				"Other",
			],
		},
		{
			fieldname: "campaign_owner",
			label: __("Campaign Owner"),
			fieldtype: "Link",
			options: "User",
		},
	],
	tree: true,
	name_field: "campaign",
	parent_field: "parent_campaign",
	initial_depth: 3,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "campaign" && data.campaign_name && data.campaign_name !== data.campaign) {
			value = `${value} <span class="text-muted">${frappe.utils.escape_html(data.campaign_name)}</span>`;
		}
		if (column.fieldname === "campaign" && data.is_group) value = `<b>${value}</b>`;
		if (column.fieldname === "roi" && flt(data.actual_cost)) {
			value = `<span class="${flt(data.roi) >= 0 ? "text-success" : "text-danger"}">${value}</span>`;
		}
		if (column.fieldname === "profit" && flt(data.profit) < 0) value = `<span class="text-danger">${value}</span>`;
		if (column.fieldname === "budget_used" && flt(data.budget_used) > 100) {
			value = `<span class="text-warning">${value}</span>`;
		}
		return value;
	},
};

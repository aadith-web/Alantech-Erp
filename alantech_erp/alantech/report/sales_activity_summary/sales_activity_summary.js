// Sales Activity Summary (CRM C10): activities and pending follow-ups per owner.
frappe.query_reports["Sales Activity Summary"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "activity_owner", label: __("Owner"), fieldtype: "Link", options: "User" },
		{
			fieldname: "reference_doctype",
			label: __("Related To"),
			fieldtype: "Select",
			options: [
				"",
				{ value: "Lead", label: __("Lead") },
				{ value: "Customer", label: __("Customer") },
				{ value: "Opportunity", label: __("Deal") },
			],
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "overdue" && data.overdue) value = `<span class="text-danger"><b>${value}</b></span>`;
		if (data && ["pending", "overdue"].includes(column.fieldname) && data[column.fieldname]) {
			const filters = { activity_owner: data.activity_owner, follow_up_done: 0, status: ["!=", "Cancelled"] };
			filters.follow_up_date = column.fieldname === "overdue" ? ["<", frappe.datetime.get_today()] : ["is", "set"];
			value = `<a href="#" onclick='frappe.route_options=${JSON.stringify(filters)};frappe.set_route("List","Sales Activity");return false;'>${value}</a>`;
		}
		return value;
	},
};

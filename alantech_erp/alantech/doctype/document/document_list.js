// Inactive/Left employees' documents are already filtered out on the server
frappe.listview_settings["Document"] = {
	add_fields: ["approval_status", "document_type", "expiry_date", "reference_doctype"],

	get_indicator(doc) {
		const colours = { "Pending Approval": "orange", Approved: "green", Rejected: "red" };
		if (!doc.approval_status) return;
		return [__(doc.approval_status), colours[doc.approval_status] || "gray",
		        `approval_status,=,${doc.approval_status}`];
	},

	formatters: {
		expiry_date(value) {
			if (!value) return "";
			const days = frappe.datetime.get_day_diff(value, frappe.datetime.get_today());
			const text = frappe.datetime.str_to_user(value);
			if (days < 0) return `<span class="text-danger">${text}</span>`;
			if (days <= 30) return `<span class="text-warning">${text}</span>`;
			return text;
		},
	},
};

// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.query_reports["Document Expiry"] = {
	filters: [
		{ fieldname: "document_type", label: __("Document Type"), fieldtype: "Link", options: "Document Type Master" },
		{ fieldname: "reference_doctype", label: __("Module Type"), fieldtype: "Link", options: "DocType" },
		{ fieldname: "expiring_within_days", label: __("Expiring Within (Days)"), fieldtype: "Int", default: 90 },
		{ fieldname: "include_expired", label: __("Include Already Expired"), fieldtype: "Check", default: 1 },
		{
			fieldname: "approval_status",
			label: __("Approval Status"),
			fieldtype: "Select",
			// the daily expiry alerts use Approved documents only
			options: ["Approved", "Approved and Pending"],
			default: "Approved",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days_left" && data && data.days_left != null) {
			// expired: red; within 30 days: orange (as the Document list colours)
			if (data.days_left < 0) value = `<span style="color: var(--red-600)">${value}</span>`;
			else if (data.days_left <= 30) value = `<span style="color: var(--orange-600)">${value}</span>`;
		}
		return value;
	},
};

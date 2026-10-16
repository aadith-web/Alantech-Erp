// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.query_reports["Document Expiry"] = {
	filters: [
		{ fieldname: "document_type", label: __("Document Type"), fieldtype: "Link", options: "Document Type" },
		{ fieldname: "reference_doctype", label: __("Module Type"), fieldtype: "Link", options: "DocType" },
		{ fieldname: "expiring_within_days", label: __("Expiring Within (Days)"), fieldtype: "Int", default: 90 },
		{ fieldname: "include_expired", label: __("Include Already Expired"), fieldtype: "Check", default: 1 },
	],
};

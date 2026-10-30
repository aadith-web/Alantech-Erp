frappe.listview_settings["Employee Asset Handover"] = {
	add_fields: ["transaction_type", "docstatus"],
	get_indicator(doc) {
		if (doc.docstatus === 2) return [__("Cancelled"), "red", "docstatus,=,2"];
		if (doc.docstatus === 0) return [__("Draft"), "gray", "docstatus,=,0"];
		return doc.transaction_type === "Issue"
			? [__("Issued"), "blue", "transaction_type,=,Issue|docstatus,=,1"]
			: [__("Received"), "green", "transaction_type,=,Receipt|docstatus,=,1"];
	},
};

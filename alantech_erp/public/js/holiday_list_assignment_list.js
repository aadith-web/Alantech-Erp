// Holiday List Assignment: badge shows Status (alt_status, setup/shifts.py) - "Active" instead of
// Frappe's "Submitted". Draft and Cancelled keep Frappe's own badges. Loaded through
// doctype_list_js in hooks.py; Frappe evaluates it with the doctype, so the form header uses it too.

frappe.listview_settings["Holiday List Assignment"] = {
	...(frappe.listview_settings["Holiday List Assignment"] || {}),
	add_fields: ["alt_status"],
	get_indicator(doc) {
		if (doc.docstatus === 1) {
			return [__("Active"), "green", "alt_status,=,Active"];
		}
	},
};

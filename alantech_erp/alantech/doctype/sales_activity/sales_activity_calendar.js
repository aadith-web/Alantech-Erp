frappe.views.calendar["Sales Activity"] = {
	field_map: {
		start: "activity_date",
		end: "ends_on",
		id: "name",
		title: "subject",
	},
	filters: [
		{ fieldtype: "Link", fieldname: "activity_owner", options: "User", label: __("Activity Owner") },
		{ fieldtype: "Select", fieldname: "activity_type", options: "\nCall\nMeeting\nTask\nNote\nEmail\nComment", label: __("Activity Type") },
	],
	get_events_method: "frappe.desk.calendar.get_events",
};

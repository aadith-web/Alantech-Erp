// Sales Activity (CRM C10): call, meeting, task, note, email or comment on a Lead, Customer or Deal.
// Server side: alantech_erp/sales/activity.py
frappe.ui.form.on("Sales Activity", {
	setup(frm) {
		frm.set_query("reference_doctype", () => ({ filters: { name: ["in", ["Lead", "Customer", "Opportunity"]] } }));
		frm.set_query("contact_person", () => ({
			query: "frappe.contacts.doctype.contact.contact.contact_query",
			filters: { link_doctype: frm.doc.reference_doctype, link_name: frm.doc.reference_name },
		}));
	},

	refresh(frm) {
		frm.toggle_enable("activity_type", frm.is_new() || !["Email", "Comment"].includes(frm.doc.activity_type));
		set_labels(frm);
		if (frm.is_new()) return;

		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			const label = frm.doc.reference_doctype === "Opportunity" ? __("Deal") : __(frm.doc.reference_doctype);
			frm.add_custom_button(label, () => frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name), __("View"));
		}
		if (frm.doc.event) frm.add_custom_button(__("Calendar Event"), () => frappe.set_route("Form", "Event", frm.doc.event), __("View"));

		const open = frm.doc.status === "Open";
		if (open && ["Call", "Meeting", "Task"].includes(frm.doc.activity_type)) {
			frm.add_custom_button(__("Complete"), () => alantech.activity.complete(frm.doc, () => frm.reload_doc()));
			frm.change_custom_button_type(__("Complete"), null, "primary");
		}
		if (frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Follow-up"), () => alantech.activity.follow_up(frm.doc, () => frm.reload_doc()), __("Create"));
		}
		if (open && frm.doc.activity_type !== "Note") {
			frm.add_custom_button(__("Cancel Activity"), () => {
				frm.set_value("status", "Cancelled");
				frm.save();
			}, __("Actions"));
		}
		if (frm.doc.follow_up_date && !frm.doc.follow_up_done && frm.doc.status !== "Cancelled") {
			const today = frappe.datetime.get_today();
			if (frm.doc.follow_up_date < today) frm.dashboard.set_headline(__("Follow-up overdue since {0}.", [frappe.datetime.str_to_user(frm.doc.follow_up_date)]), "red");
			else if (frm.doc.follow_up_date === today) frm.dashboard.set_headline(__("Follow-up due today."), "orange");
		}
	},

	activity_type(frm) {
		set_labels(frm);
		if (["Note", "Email", "Comment"].includes(frm.doc.activity_type)) frm.set_value("status", "Completed");
	},

	activity_date(frm) {
		if (["Call", "Meeting"].includes(frm.doc.activity_type) && frm.doc.activity_date) {
			frm.set_value("ends_on", moment(frm.doc.activity_date).add(30, "minutes").format("YYYY-MM-DD HH:mm:ss"));
		}
	},

	reference_name(frm) {
		frm.set_value("contact_person", null);
	},
});

function set_labels(frm) {
	const task = frm.doc.activity_type === "Task";
	frm.set_df_property("follow_up_date", "label", task ? __("Due Date") : __("Follow-up Due Date"));
	frm.set_df_property("activity_date", "label", task ? __("Start") : __("Date"));
	frm.toggle_reqd("follow_up_date", task);
}

// Sales Activity list (CRM C10): overdue follow-ups in red, due today in orange.
frappe.listview_settings["Sales Activity"] = {
	add_fields: ["status", "activity_type", "follow_up_date", "follow_up_done", "activity_date"],
	get_indicator(doc) {
		if (doc.status === "Cancelled") return [__("Cancelled"), "gray", "status,=,Cancelled"];
		const today = frappe.datetime.get_today();
		const pending =
			(doc.activity_type === "Task" && doc.status === "Open") ||
			(doc.follow_up_date && !cint(doc.follow_up_done));
		if (pending && doc.follow_up_date) {
			if (doc.follow_up_date < today) return [__("Overdue"), "red", "follow_up_date,<,Today"];
			if (doc.follow_up_date === today) return [__("Due Today"), "orange", "follow_up_date,=,Today"];
		}
		if (doc.status === "Open") return [__("Open"), "blue", "status,=,Open"];
		return [__("Completed"), "green", "status,=,Completed"];
	},
	onload(listview) {
		listview.page.add_inner_button(__("My Follow-ups"), () => {
			listview.filter_area.clear(false).then(() =>
				listview.filter_area.add([
					["Sales Activity", "activity_owner", "=", frappe.session.user],
					["Sales Activity", "follow_up_done", "=", 0],
					["Sales Activity", "status", "!=", "Cancelled"],
					["Sales Activity", "follow_up_date", "is", "set"],
				])
			);
		});
	},
};

// Employee Asset Handover: Issue assets to an employee or receive them back.
// The Asset Movement (and Asset Repair for damaged returns) is created on submit by the server.

frappe.ui.form.on("Employee Asset Handover", {
	setup(frm) {
		// created by this document and cancelled/removed by it, so skip the "cancel all linked" prompt
		frm.ignore_doctypes_on_cancel_all = ["Asset Movement", "Asset Repair"];

		frm.set_query("employee", () => ({ filters: { status: ["!=", "Inactive"] } }));
		frm.set_query("location", () => ({
			query: "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover.location_query",
		}));
		frm.set_query("asset", "items", () => ({
			query: "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover.asset_query",
			filters: {
				transaction_type: frm.doc.transaction_type,
				employee: frm.doc.employee,
				company: frm.doc.company,
			},
		}));
	},

	onload(frm) {
		// opened from Employee > Receive Assets: fill the table straight away
		if (frm.is_new() && frm.doc.transaction_type === "Receipt" && frm.doc.employee && !(frm.doc.items || []).some((r) => r.asset)) {
			frm.trigger("get_assets_held");
		}
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.asset_movement) {
			frm.add_custom_button(__("Asset Movement"), () => frappe.set_route("Form", "Asset Movement", frm.doc.asset_movement), __("View"));
		}
		if (!frm.is_new()) {
			frm.add_custom_button(__("Asset Repairs"), () => frappe.set_route("List", "Asset Repair", { alt_responsible_employee: frm.doc.employee }), __("View"));
		}
	},

	transaction_type(frm) {
		// the asset list depends on the type, so start over
		frm.clear_table("items");
		frm.refresh_field("items");
		if (frm.doc.transaction_type === "Receipt" && frm.doc.employee) frm.trigger("get_assets_held");
	},

	employee(frm) {
		frm.clear_table("items");
		frm.refresh_field("items");
		if (frm.doc.transaction_type === "Receipt" && frm.doc.employee) frm.trigger("get_assets_held");
	},

	inspection_required(frm) {
		if (frm.doc.inspection_required) {
			if (!frm.doc.inspected_by) frm.set_value("inspected_by", frappe.session.user);
			if (!frm.doc.inspection_date) frm.set_value("inspection_date", frappe.datetime.get_today());
		}
		frm.refresh_field("items");
	},

	get_assets_held(frm) {
		if (!frm.doc.employee) return;
		frappe
			.call({
				method: "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover.get_employee_assets",
				args: { employee: frm.doc.employee },
			})
			.then(({ message: assets = [] }) => {
				frm.clear_table("items");
				assets.forEach((a) =>
					frm.add_child("items", { asset: a.asset, asset_name: a.asset_name, current_location: a.location })
				);
				frm.refresh_field("items");
				frappe.show_alert({
					message: assets.length
						? __("{0} asset(s) held by {1}", [assets.length, frm.doc.employee_name || frm.doc.employee])
						: __("{0} holds no assets", [frm.doc.employee_name || frm.doc.employee]),
					indicator: assets.length ? "blue" : "green",
				});
			});
	},
});

frappe.ui.form.on("Employee Asset Handover Item", {
	condition(frm, cdt, cdn) {
		if (locals[cdt][cdn].condition !== "Damaged") frappe.model.set_value(cdt, cdn, "issue_description", "");
	},
});

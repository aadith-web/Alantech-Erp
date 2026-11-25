// Employee Asset Handover: Issue assets to an employee or receive them back.
// The Asset Movement (and Asset Repair for damaged returns) is created on submit by the server.

frappe.ui.form.on("Employee Asset Handover", {
	setup(frm) {
		// created by this document and cancelled/removed by it, so skip the "cancel all linked" prompt
		frm.ignore_doctypes_on_cancel_all = ["Asset Movement", "Asset Repair"];

		frm.set_query("employee", () => ({ filters: { status: ["!=", "Inactive"] } }));
		frm.set_query("return_location", "items", () => ({
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
		alt_handover_columns(frm);
		if (frm.doc.docstatus === 1 && frm.doc.asset_movement) {
			frm.add_custom_button(__("Asset Movement"), () => frappe.set_route("Form", "Asset Movement", frm.doc.asset_movement), __("View"));
		}
		if (!frm.is_new()) {
			frm.add_custom_button(__("Asset Repairs"), () => frappe.set_route("List", "Asset Repair", { alt_responsible_employee: frm.doc.employee }), __("View"));
		}
	},

	transaction_type(frm) {
		alt_handover_columns(frm);
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
		alt_handover_columns(frm);
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
					frm.add_child("items", {
						asset: a.asset, asset_name: a.asset_name, current_location: a.location,
						return_location: a.location,
						qty: a.qty || 1, available_qty: a.qty || 1,
					})
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

// Assets table columns that only apply to some handovers are shown only then, so the table never
// shows empty columns that cannot be edited: Return To Location on a Receipt; Condition and Issue / Damage Details on a Receipt with
// "Inspect Assets on Return" ticked (Issue / Damage Details is filled for Damaged rows); Asset Repair
// once one was created (on submit of a Receipt with a Damaged asset).
function alt_handover_columns(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;
	const inspect = frm.doc.transaction_type === "Receipt" && !!frm.doc.inspection_required;
	const repairs = (frm.doc.items || []).some((r) => r.asset_repair);
	const receipt = frm.doc.transaction_type === "Receipt";
	const wanted = { return_location: receipt, condition: inspect, issue_description: inspect, asset_repair: repairs };
	const field = (name) => grid.docfields.find((d) => d.fieldname === name);
	const changed = Object.entries(wanted).filter(([name, show]) => !!field(name) && !field(name).hidden !== show);
	if (!changed.length) return;
	changed.forEach(([name, show]) => {
		field(name).hidden = show ? 0 : 1; // the grid's own copy (update_docfield_property skips it before the rows exist)
		grid.update_docfield_property(name, "hidden", show ? 0 : 1);
	});
	grid.reset_grid();
}

const ALT_HANDOVER = "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover";

frappe.ui.form.on("Employee Asset Handover Item", {
	// details as soon as the asset is picked, not only after Save (ClickUp 14yr2e58az7 / 14yr2e58hbm)
	asset(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.asset) {
			["asset_name", "current_location", "return_location", "available_qty"].forEach((f) => frappe.model.set_value(cdt, cdn, f, null));
			return;
		}
		frappe
			.xcall(`${ALT_HANDOVER}.get_asset_details`, {
				asset: row.asset,
				transaction_type: frm.doc.transaction_type,
				employee: frm.doc.employee || null,
			})
			.then((d) => {
				if (!d || locals[cdt][cdn].asset !== row.asset) return;
				frappe.model.set_value(cdt, cdn, {
					asset_name: d.asset_name,
					current_location: d.current_location,
					// Receipt: back to where the asset is recorded, changeable per row (ClickUp 14yr2e58hwg)
					return_location: frm.doc.transaction_type === "Receipt" ? d.current_location : null,
					available_qty: d.available_qty,
					// Receipt: everything the employee holds; Issue: 1 to start with
					qty: frm.doc.transaction_type === "Receipt" ? d.available_qty || 1 : 1,
				});
			});
	},

	qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.asset || row.available_qty == null) return;
		if (cint(row.qty) > cint(row.available_qty)) {
			frappe.msgprint({
				title: __("Quantity Not Available"),
				indicator: "orange",
				message: frm.doc.transaction_type === "Receipt"
					? __("Row {0}: {1} holds only {2} of asset {3}.", [row.idx, frm.doc.employee_name || frm.doc.employee, row.available_qty, row.asset])
					: __("Row {0}: only {1} of asset {2} available.", [row.idx, row.available_qty, row.asset]),
			});
			frappe.model.set_value(cdt, cdn, "qty", cint(row.available_qty) || 1);
		} else if (cint(row.qty) < 1) {
			frappe.model.set_value(cdt, cdn, "qty", 1);
		}
	},

	condition(frm, cdt, cdn) {
		if (locals[cdt][cdn].condition !== "Damaged") frappe.model.set_value(cdt, cdn, "issue_description", "");
	},
});

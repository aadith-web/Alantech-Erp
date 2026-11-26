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
		// opened from Employee > Return Assets: fill the table straight away
		if (frm.is_new() && frm.doc.transaction_type === "Receipt" && frm.doc.employee && !(frm.doc.items || []).some((r) => r.asset)) {
			frm.trigger("get_assets_held");
		}
		alt_first_asset_row(frm);
	},

	refresh(frm) {
		alt_handover_columns(frm);
		alt_total_assets(frm);
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
		alt_first_asset_row(frm);
		frm.refresh_field("items");
		if (frm.doc.transaction_type === "Receipt" && frm.doc.employee) frm.trigger("get_assets_held");
	},

	employee(frm) {
		frm.clear_table("items");
		alt_first_asset_row(frm);
		frm.refresh_field("items");
		if (frm.doc.transaction_type === "Receipt" && frm.doc.employee) frm.trigger("get_assets_held");
	},

	items_remove(frm) {
		alt_total_assets(frm);
	},

	validate(frm) {
		// drop rows left without an asset (e.g. the first empty row) before the mandatory check;
		// with no asset at all the server says "Add at least one asset in the Assets table."
		const empty = (frm.doc.items || []).filter((r) => !r.asset);
		if (!empty.length) return;
		empty.forEach((r) => frappe.model.clear_doc(r.doctype, r.name));
		frm.doc.items = (frm.doc.items || []).filter((r) => r.asset);
		frm.doc.items.forEach((r, i) => (r.idx = i + 1));
		frm.refresh_field("items");
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
						warranty: a.warranty, warranty_expiry_date: a.warranty_expiry_date,
						qty: a.qty || 1, available_qty: a.qty || 1,
					})
				);
				frm.refresh_field("items");
				alt_total_assets(frm);
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
// shows empty columns that cannot be edited: Return To Location on a Receipt; Damage Details while a
// row is Damaged (Condition, Good / Damaged, is always shown: ClickUp 14yr2e58jx0); Asset Repair once
// one was created (on submit of a Receipt with a Damaged asset).
function alt_handover_columns(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;
	const repairs = (frm.doc.items || []).some((r) => r.asset_repair);
	const receipt = frm.doc.transaction_type === "Receipt";
	const damaged = (frm.doc.items || []).some((r) => r.condition === "Damaged");
	const wanted = { return_location: receipt, issue_description: damaged, asset_repair: repairs };
	const field = (name) => grid.docfields.find((d) => d.fieldname === name);
	const changed = Object.entries(wanted).filter(([name, show]) => !!field(name) && !field(name).hidden !== show);
	if (!changed.length) return;
	changed.forEach(([name, show]) => {
		field(name).hidden = show ? 0 : 1; // the grid's own copy (update_docfield_property skips it before the rows exist)
		grid.update_docfield_property(name, "hidden", show ? 0 : 1);
	});
	grid.reset_grid();
}

// A new Issue starts with one empty asset row to fill, instead of an empty "No rows" table
// (ClickUp 14yr2e58jwx). A Receipt is filled by Get Assets Held.
function alt_first_asset_row(frm) {
	if (!frm.is_new() || frm.doc.transaction_type !== "Issue" || (frm.doc.items || []).length) return;
	frm.add_child("items");
	frm.refresh_field("items");
}

// Total Assets = number of assets in the table, kept up to date while editing (ClickUp 14yr2e58jwz)
function alt_total_assets(frm) {
	if (frm.doc.docstatus !== 0) return;
	const total = (frm.doc.items || []).filter((r) => r.asset).length;
	if (cint(frm.doc.total_assets) !== total) frm.set_value("total_assets", total);
}

const ALT_HANDOVER = "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover";

// Warranty Expiry in red once it has passed (ClickUp 14yr2e58k7e)
frappe.ui.form.on("Employee Asset Handover", {
	setup() {
		const df = frappe.meta.get_docfield("Employee Asset Handover Item", "warranty_expiry_date");
		if (!df) return;
		df.formatter = (value) => {
			if (!value) return "";
			const text = frappe.datetime.str_to_user(value);
			return value < frappe.datetime.get_today()
				? `<span class="text-danger" title="${__("Warranty expired")}">${text} (${__("Expired")})</span>`
				: text;
		};
	},
});

frappe.ui.form.on("Employee Asset Handover Item", {
	// details as soon as the asset is picked, not only after Save (ClickUp 14yr2e58az7 / 14yr2e58hbm)
	asset(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.asset) {
			["asset_name", "current_location", "return_location", "available_qty", "warranty", "warranty_expiry_date"].forEach((f) => frappe.model.set_value(cdt, cdn, f, null));
			alt_total_assets(frm);
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
					warranty: d.warranty,
					warranty_expiry_date: d.warranty_expiry_date,
					// Receipt: everything the employee holds; Issue: 1 to start with
					qty: frm.doc.transaction_type === "Receipt" ? d.available_qty || 1 : 1,
				});
				if (d.warranty_expired && frm.doc.transaction_type === "Issue") {
					frappe.show_alert({
						message: __("Row {0}: the warranty of asset {1} expired on {2}.", [
							row.idx, row.asset, frappe.datetime.str_to_user(d.warranty_expiry_date)]),
						indicator: "orange",
					}, 8);
				}
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
		const row = locals[cdt][cdn];
		if (row.condition !== "Damaged") frappe.model.set_value(cdt, cdn, "issue_description", "");
		alt_handover_columns(frm); // Damage Details column only while a row is Damaged
		if (row.condition === "Damaged") frm.fields_dict.items.grid.grid_rows_by_docname[cdn]?.show_form();
	},
});

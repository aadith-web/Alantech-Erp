// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt
// Costing formulas live in public/js/estimation_pricing.js.

const ALT_EST_METHOD = "alantech_erp.alantech.doctype.estimation.estimation";

frappe.ui.form.on("Estimation", {
	setup(frm) {
		frm.set_query("opportunity", () => ({
			filters: { status: ["not in", ["Lost", "Closed", "Converted"]] },
		}));
		frm.set_query("plant_assembly", () => ({ filters: { disabled: 0 } }));
		frm.set_query("quote_item", () => ({ filters: { is_sales_item: 1, disabled: 0 } }));
		frm.set_query("sub_assembly", "sections", () => ({ filters: { disabled: 0 } }));
	},

	refresh(frm) {
		alantech.estimation.sync_sections(frm);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Add Sub Assembly"), () => add_sub_assembly(frm), __("Cost Sheet"));
			if ((frm.doc.items || []).length) {
				frm.add_custom_button(__("Remove Unused Rows"), () => remove_zero_rows(frm), __("Cost Sheet"));
			}
		}

		if (!frm.is_new() && frappe.model.can_create("Technical Offer")) {
			frm.add_custom_button(
				__("Technical Offer"),
				() => frappe.model.open_mapped_doc({ method: `${ALT_EST_METHOD}.make_technical_offer`, frm }),
				__("Create")
			);
		}
		if (frm.doc.docstatus === 1 && frappe.model.can_create("Quotation")) {
			frm.add_custom_button(
				__("Quotation"),
				() => frappe.model.open_mapped_doc({ method: `${ALT_EST_METHOD}.make_quotation`, frm }),
				__("Create")
			);
			frm.page.set_inner_btn_group_as_primary(__("Create"));
		}
		if (!frm.is_new() && frappe.model.can_create("Plant Assembly")) {
			frm.add_custom_button(__("Save as Plant Assembly"), () => save_as_assembly(frm), __("Create"));
		}
	},

	plant_assembly(frm) {
		if (!frm.doc.plant_assembly || frm.doc.docstatus !== 0) return;
		const load = () =>
			frm.call("apply_plant_assembly").then(() => {
				frm.dirty();
				alantech.estimation.sync_sections(frm);
				frm.refresh_fields();
				frappe.show_alert({
					message: __("Loaded Plant Assembly {0}", [frappe.utils.escape_html(frm.doc.plant_assembly)]),
					indicator: "green",
				});
			});

		if ((frm.doc.items || []).length || (frm.doc.sections || []).length) {
			frappe.confirm(
				__("Replace the sub assemblies and cost items with Plant Assembly {0}?", [
					frappe.utils.escape_html(frm.doc.plant_assembly),
				]),
				load
			);
		} else {
			load();
		}
	},
});

function add_sub_assembly(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Add Sub Assembly"),
		fields: [
			{
				fieldname: "sub_assembly",
				fieldtype: "Link",
				options: "Sub Assembly",
				label: __("Sub Assembly"),
				reqd: 1,
				get_query: () => ({ filters: { disabled: 0 } }),
				onchange() {
					const name = dialog.get_value("sub_assembly");
					if (!name) return;
					frappe.db.get_value("Sub Assembly", name, ["offer_title", "default_pricing_mode"]).then(({ message }) => {
						if (!message) return;
						dialog.set_value("section_title", message.offer_title || name);
						dialog.set_value("pricing_mode", message.default_pricing_mode || "Included");
					});
				},
			},
			{
				fieldname: "section_title",
				fieldtype: "Data",
				label: __("Section Title"),
				description: __("Use a new title to add the same sub assembly again, e.g. RO System - RO 2"),
			},
			{
				fieldname: "pricing_mode",
				fieldtype: "Select",
				label: __("Pricing"),
				options: ["Included", "Separate Line", "Optional"],
				default: "Included",
			},
		],
		primary_action_label: __("Add"),
		primary_action(values) {
			frm.call("add_sub_assembly", values).then(() => {
				dialog.hide();
				frm.dirty();
				alantech.estimation.sync_sections(frm);
				frm.refresh_fields();
			});
		},
	});
	dialog.show();
}

function remove_zero_rows(frm) {
	frappe.confirm(__("Remove cost items with no quantity or no unit cost?"), () =>
		frm.call("remove_zero_rows").then(({ message }) => {
			frm.dirty();
			frm.refresh_fields();
			frappe.show_alert({ message: __("Removed {0} rows", [message || 0]), indicator: "green" });
		})
	);
}

function save_as_assembly(frm) {
	frappe.prompt(
		{
			fieldname: "assembly_name",
			fieldtype: "Data",
			label: __("Assembly Name"),
			reqd: 1,
			default: frm.doc.plant_type,
			description: __("Plant type, e.g. UF + RO + EDI 160 m³/h"),
		},
		({ assembly_name }) =>
			frappe
				.call(`${ALT_EST_METHOD}.make_plant_assembly`, { source_name: frm.doc.name, assembly_name })
				.then(({ message }) => {
					let msg = __("Plant Assembly {0} saved", [message.name]);
					if (message.skipped.length) {
						msg += ". " + __("Left out (no Sub Assembly): {0}", [message.skipped.join(", ")]);
					}
					frappe.show_alert({ message: msg, indicator: "green" });
				}),
		__("Save as Plant Assembly"),
		__("Save")
	);
}

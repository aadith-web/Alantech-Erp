// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Proposal Settings", {
	setup(frm) {
		["scope_of_supply_terms", "commercial_terms"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { disabled: 0 } }))
		);
	},

	load_library(frm) {
		frappe.confirm(
			__("Add the standard water treatment sub assemblies, plant assemblies and terms? Records that already exist are not changed."),
			() =>
				frappe
					.call({
						method: "alantech_erp.alantech.doctype.proposal_settings.proposal_settings.load_standard_library",
						freeze: true,
						freeze_message: __("Loading standard library..."),
					})
					.then(({ message }) => {
						frappe.msgprint({
							title: __("Standard Library"),
							indicator: "green",
							message: __("Added {0} sub assemblies, {1} plant assemblies and {2} terms templates.", [
								message.sub_assemblies,
								message.plant_assemblies,
								message.terms,
							]),
						});
						frm.reload_doc();
					})
		);
	},
});

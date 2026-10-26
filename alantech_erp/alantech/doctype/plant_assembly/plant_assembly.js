// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Plant Assembly", {
	setup(frm) {
		frm.set_query("sub_assembly", "sections", () => ({ filters: { disabled: 0 } }));
		frm.set_query("quote_item", () => ({ filters: { is_sales_item: 1, disabled: 0 } }));
		["scope_of_supply_terms", "commercial_terms"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { disabled: 0 } }))
		);
	},
});

frappe.ui.form.on("Plant Assembly Section", {
	sub_assembly(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.sub_assembly) return;
		frappe.db
			.get_value("Sub Assembly", row.sub_assembly, ["offer_title", "default_pricing_mode", "include_in_offer"])
			.then(({ message }) => {
				if (!message) return;
				frappe.model.set_value(cdt, cdn, {
					section_title: row.section_title || message.offer_title || row.sub_assembly,
					pricing_mode: message.default_pricing_mode || "Included",
					include_in_offer: message.include_in_offer,
				});
			});
	},
});

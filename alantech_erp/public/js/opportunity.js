// Deal (Opportunity): the Sales Manager prepares the Estimation; the Quotation is made from it.

frappe.ui.form.on("Opportunity", {
	refresh(frm) {
		if (frm.is_new() || ["Lost", "Closed", "Converted"].includes(frm.doc.status)) return;

		// Quotations are made from the submitted Estimation, not straight from the Deal
		frm.remove_custom_button(__("Quotation"), __("Create"));

		if (frappe.model.can_create("Estimation")) {
			frm.add_custom_button(
				__("Estimation"),
				() => frappe.new_doc("Estimation", { opportunity: frm.doc.name }),
				__("Create")
			);
		}

		if (!frappe.model.can_create("Quotation")) return;
		frappe.db
			.get_list("Estimation", {
				filters: { opportunity: frm.doc.name, docstatus: 1 },
				fields: ["name"],
				order_by: "creation desc",
				limit: 1,
			})
			.then((rows) => {
				if (!rows.length) return;
				frm.add_custom_button(
					__("Quotation"),
					() =>
						frappe.model.open_mapped_doc({
							method: "alantech_erp.alantech.doctype.estimation.estimation.make_quotation",
							source_name: rows[0].name,
						}),
					__("Create")
				);
			});
	},
});

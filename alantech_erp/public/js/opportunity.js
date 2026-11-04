// Deal (Opportunity): created from the Quotation (Create Deal), not the other way round.
// Its amount and Sales Stage follow the quotation; the Estimation belongs to the Customer.
// No Prospect flow (alantech_erp/sales/prospect.py).

// Alantech sales stages, in pipeline order (alantech_erp/sales/__init__.py SALES_STAGES)
const ALT_SALES_STAGES = [
	"Quotation Draft",
	"Quotation Revision",
	"Quotation Approval",
	"Quotation Approved",
	"Quotation Sent",
	"Client Accepted",
	"Lost",
];

frappe.ui.form.on("Opportunity", {
	setup(frm) {
		frm.set_query("opportunity_from", () => ({ filters: { name: ["in", ["Customer", "Lead"]] } }));
		frm.set_query("sales_stage", () => ({ filters: { name: ["in", ALT_SALES_STAGES] } }));
	},

	refresh(frm) {
		if (frm.is_new()) return;

		// ERPNext adds its buttons after this handler runs
		setTimeout(() => frm.remove_custom_button(__("Quotation"), __("Create")), 0);

		if (frm.doc.alt_quotation) {
			frm.add_custom_button(__("Quotation"), () => frappe.set_route("Form", "Quotation", frm.doc.alt_quotation), __("View"));
			frm.set_intro(
				__("Created from Quotation {0}; the amount and the Sales Stage follow the quotation and its revisions.", [
					`<b>${frappe.utils.escape_html(frm.doc.alt_quotation)}</b>`,
				]),
				"blue"
			);
		}
	},
});

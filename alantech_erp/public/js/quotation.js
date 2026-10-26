// Quotation: two-level approval flow (alantech_erp/sales).
// Level 1 manager approval and Level 2 client approval run through the "ALT Quotation Approval" workflow.

const ALT_CLIENT_APPROVED = "Client Approved";

frappe.ui.form.on("Quotation", {
	setup(frm) {
		frm.set_query("alt_estimation", () => ({
			filters: { docstatus: 1, opportunity: frm.doc.opportunity || "" },
		}));
		frm.set_query("alt_technical_offer", () => ({
			filters: {
				docstatus: ["<", 2],
				...(frm.doc.alt_estimation ? { estimation: frm.doc.alt_estimation } : { opportunity: frm.doc.opportunity || "" }),
			},
		}));
	},

	refresh(frm) {
		if (!frm.doc.workflow_state) return; // workflow not active on this site

		// ERPNext adds its buttons after this handler runs; tidy up once they are on the page.
		setTimeout(() => {
			if (frm.doc.docstatus === 0) {
				// Items must come from the Estimation, not straight from the Deal
				frm.remove_custom_button(__("Opportunity"), __("Get Items From"));
			}
			if (frm.doc.docstatus === 1) {
				// Approved prices are fixed; changes go through "Client Requested Revision"
				frm.remove_custom_button(__("Update Items"));
				if (frm.doc.workflow_state !== ALT_CLIENT_APPROVED) {
					frm.remove_custom_button(__("Sales Order"), __("Create"));
				}
			}
		}, 0);

		if (frm.doc.alt_estimation && frm.doc.docstatus === 0) {
			frm.set_intro(
				__("Priced from Estimation {0}. Submit for approval when ready; the Sales Manager approves before it goes to the client.", [
					`<b>${frappe.utils.escape_html(frm.doc.alt_estimation)}</b>`,
				]),
				"blue"
			);
		}
	},

	opportunity(frm) {
		if (frm.doc.alt_estimation) frm.set_value("alt_estimation", null);
	},
});

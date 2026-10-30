// Quotation: approval flow (alantech_erp/sales, ClickUp CRM-F07).
// Level 1 Sales Manager, Level 2 above the Selling Settings limit, then the client decision,
// all through the "ALT Quotation Approval" workflow.

const ALT_CLIENT_APPROVED = "Client Approved";
const ALT_REJECTED = "Rejected";
const ALT_PENDING_MANAGER = "Pending Manager Approval";
const ALT_PENDING_LEVEL_2 = "Pending Level 2 Approval";
const ALT_REJECT_ACTION = "Reject";

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

		alt_show_approval_intro(frm);
	},

	opportunity(frm) {
		if (frm.doc.alt_estimation) frm.set_value("alt_estimation", null);
	},

	// Reject needs remarks: ask for them, store them, then let the workflow action run.
	before_workflow_action(frm) {
		if (frm.selected_workflow_action !== ALT_REJECT_ACTION) return;

		frappe.dom.unfreeze(); // the workflow froze the page; the dialog has to be usable
		return new Promise((resolve, reject) => {
			let done = false;
			const dialog = frappe.prompt(
				{
					fieldname: "remarks",
					fieldtype: "Small Text",
					label: __("Reason for Rejection"),
					description: __("The salesperson sees this and resubmits after the changes."),
					reqd: 1,
				},
				({ remarks }) => {
					done = true;
					frappe
						.call({
							method: "alantech_erp.sales.quotation.set_rejection_remarks",
							args: { name: frm.doc.name, remarks },
							freeze: true,
						})
						.then(() => {
							frappe.dom.freeze(); // balanced by the workflow's own unfreeze
							resolve();
						}, reject);
				},
				__("Reject Quotation {0}", [frm.doc.name]),
				__("Reject")
			);
			dialog.onhide = () => {
				if (!done) reject(); // cancelled: no workflow action
			};
		});
	},
});

function alt_show_approval_intro(frm) {
	const esc = frappe.utils.escape_html;
	const state = frm.doc.workflow_state;

	if (state === ALT_REJECTED && frm.doc.alt_rejection_remarks) {
		frm.set_intro(
			__("Rejected by {0}: {1}<br>Make the changes and use <b>Resubmit</b>.", [
				esc(frappe.user.full_name(frm.doc.alt_rejected_by) || frm.doc.alt_rejected_by || ""),
				esc(frm.doc.alt_rejection_remarks),
			]),
			"red"
		);
		return;
	}
	if (state === ALT_PENDING_MANAGER) {
		frm.set_intro(
			frm.doc.alt_approval_level === "Level 2"
				? __("Waiting for Sales Manager approval (Level 1). It is above the Level 2 limit, so a Level 2 approver signs off next.")
				: __("Waiting for Sales Manager approval."),
			"orange"
		);
		return;
	}
	if (state === ALT_PENDING_LEVEL_2) {
		frm.set_intro(
			__("Approved by {0} (Level 1). Waiting for Level 2 approval.", [
				esc(frappe.user.full_name(frm.doc.alt_level_1_approver) || frm.doc.alt_level_1_approver || ""),
			]),
			"orange"
		);
		return;
	}
	if (frm.doc.alt_estimation && frm.doc.docstatus === 0) {
		frm.set_intro(
			__("Priced from Estimation {0}. Submit for approval when ready; the Sales Manager approves before it goes to the client.", [
				`<b>${esc(frm.doc.alt_estimation)}</b>`,
			]),
			"blue"
		);
	}
}

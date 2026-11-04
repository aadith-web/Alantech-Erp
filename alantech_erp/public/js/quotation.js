// Quotation: approval flow and Deal (alantech_erp/sales, ClickUp CRM-F05 / F06 / F07).
// Made from a submitted Estimation, a Technical Offer, or directly. Level 1 by the creator's
// Sales Manager, Level 2 (above the Selling Settings limit) by the Sales Director, both from the
// Sales Person tree; then the client decision, all through the "ALT Quotation Approval" workflow.
// Create Deal makes the (optional) Deal from the quotation.

const ALT_CLIENT_APPROVED = "Client Approved";
const ALT_REJECTED = "Rejected";
const ALT_PENDING_MANAGER = "Pending Manager Approval";
const ALT_PENDING_LEVEL_2 = "Pending Level 2 Approval";
const ALT_REJECT_ACTION = "Reject";

frappe.ui.form.on("Quotation", {
	setup(frm) {
		// no Prospect flow (alantech_erp/sales/prospect.py)
		frm.set_query("quotation_to", () => ({
			filters: { name: ["in", ["Customer", "Lead", "CRM Deal"]] },
		}));
		frm.set_query("alt_estimation", () => ({
			filters: {
				docstatus: 1,
				customer: frm.doc.quotation_to === "Customer" ? frm.doc.party_name || "" : "__none__",
			},
		}));
		frm.set_query("alt_technical_offer", () => ({
			filters: {
				docstatus: ["<", 2],
				...(frm.doc.alt_estimation
					? { estimation: frm.doc.alt_estimation }
					: { customer: frm.doc.quotation_to === "Customer" ? frm.doc.party_name || "" : "__none__" }),
			},
		}));
	},

	refresh(frm) {
		alt_add_deal_button(frm);
		if (!frm.doc.workflow_state) return; // workflow not active on this site

		// ERPNext adds its buttons after this handler runs; tidy up once they are on the page.
		setTimeout(() => {
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

	party_name(frm) {
		if (frm.doc.alt_estimation) frm.set_value("alt_estimation", null);
		if (frm.doc.alt_technical_offer) frm.set_value("alt_technical_offer", null);
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
	const name_of = (user) => esc(frappe.user.full_name(user) || user || "");
	const manager = frm.doc.alt_level_1_user ? name_of(frm.doc.alt_level_1_user) : __("a Sales Manager");
	const director = frm.doc.alt_level_2_user ? name_of(frm.doc.alt_level_2_user) : __("the Sales Director");
	if (state === ALT_PENDING_MANAGER) {
		frm.set_intro(
			frm.doc.alt_approval_level === "Level 2"
				? __("Waiting for approval by {0} (Level 1). It is above the Level 2 limit, so {1} signs off next.", [manager, director])
				: __("Waiting for approval by {0}.", [manager]),
			"orange"
		);
		return;
	}
	if (state === ALT_PENDING_LEVEL_2) {
		frm.set_intro(
			__("Approved by {0} (Level 1). Waiting for Level 2 approval by {1}.", [
				name_of(frm.doc.alt_level_1_approver),
				director,
			]),
			"orange"
		);
		return;
	}
	if (frm.doc.docstatus === 0 && frm.doc.quotation_to === "Lead") {
		frm.set_intro(
			__("Convert the Lead to a Customer (Company or Individual) before this quotation goes for approval."),
			"orange"
		);
		return;
	}
	if (frm.doc.docstatus === 0 && !frm.is_new()) {
		frm.set_intro(
			frm.doc.alt_estimation
				? __("Priced from Estimation {0}. Submit for approval when ready; {1} approves before it goes to the client.", [
						`<b>${esc(frm.doc.alt_estimation)}</b>`,
						manager,
				  ])
				: __("Submit for approval when ready; {0} approves before it goes to the client.", [manager]),
			"blue"
		);
	}
}

// Create Deal: the optional Deal, filled from the quotation (amount = quote value).
function alt_add_deal_button(frm) {
	if (frm.is_new() || frm.doc.docstatus === 2 || frm.doc.quotation_to !== "Customer") return;
	if (frm.doc.opportunity) {
		frm.add_custom_button(__("Deal"), () => frappe.set_route("Form", "Opportunity", frm.doc.opportunity), __("View"));
		return;
	}
	if (!frappe.model.can_create("Opportunity")) return;
	frm.add_custom_button(__("Create Deal"), () => {
		const dialog = new frappe.ui.Dialog({
			title: __("Create Deal"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${__(
						"Deal amount: {0}. The amount and the Sales Stage follow this quotation (approval, client, revisions).",
						[format_currency(frm.doc.grand_total, frm.doc.currency)]
					)}</p>`,
				},
				{ fieldname: "probability", fieldtype: "Percent", label: __("Probability"), default: 50, reqd: 1 },
				{
					fieldname: "expected_closing",
					fieldtype: "Date",
					label: __("Expected Closing Date"),
					default: frm.doc.valid_till,
				},
				{
					fieldname: "opportunity_owner",
					fieldtype: "Link",
					options: "User",
					label: __("Deal Owner"),
					default: frm.doc.owner,
				},
			],
			primary_action_label: __("Create"),
			primary_action(values) {
				frappe
					.call({
						method: "alantech_erp.sales.deal.make_deal",
						args: { quotation: frm.doc.name, ...values },
						freeze: true,
					})
					.then(({ message }) => {
						dialog.hide();
						frappe.show_alert({ message: __("Deal {0} created", [message]), indicator: "green" });
						frm.reload_doc();
					});
			},
		});
		dialog.show();
	});
}

// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Document", {
	setup(frm) {
		// Only these record types can have documents; edit the list as needed
		const ALLOWED = ["Employee", "Supplier", "Customer", "Company"];
		frm.set_query("reference_doctype", () => ({ filters: { name: ["in", ALLOWED] } }));
		frm.set_query("document_type", () => ({ filters: { disabled: 0 } }));
	},

	onload(frm) {
		if (frm.is_new() && frm.doc.reference_doctype === "Employee" && !frm.doc.reference_name) {
			frappe.db.get_value("Employee", { user_id: frappe.session.user }, "name").then((r) => {
				const employee = r.message && r.message.name;
				if (employee && !frm.doc.reference_name) frm.set_value("reference_name", employee);
			});
		}
	},

	refresh(frm) {
		frm.__alt_ref_dt = frm.doc.reference_doctype;
		frm.toggle_enable("reference_doctype", frm.is_new() && !frappe.route_options?.reference_doctype);
		alt_doc.set_card_number_label(frm);
		alt_doc.take_snapshot(frm);
		alt_doc.show_status_intro(frm);
		alt_doc.add_review_buttons(frm);
	},

	document_type(frm) {
		alt_doc.set_card_number_label(frm);
	},

	reference_doctype(frm) {
		// Clear "Belongs To" only when the user switches Module Type (e.g. Employee -> Supplier),
		// not when the form opens with values passed in (Upload button, Documents tab)
		const previous = frm.__alt_ref_dt;
		frm.__alt_ref_dt = frm.doc.reference_doctype;
		if (previous && previous !== frm.doc.reference_doctype && frm.doc.reference_name) {
			frm.set_value("reference_name", "");
		}
	},

	validate(frm) {
		if (!frm.is_new() && alt_doc.snapshot_of(frm) === frm.__alt_doc_snapshot) {
			frappe.throw({ title: __("Nothing to save"), message: __("No changes to save."), indicator: "orange" });
		}
	},
});
const ALT_DOC_STATUS = { PENDING: "Pending Approval", APPROVED: "Approved", REJECTED: "Rejected" };

// Server-set fields, ignored by the "has anything changed?" check
const ALT_DOC_SYSTEM_FIELDS = new Set([
	"reference_title", "employee", "expiry_required",
	"approval_status", "submitted_by", "reviewed_by", "reviewed_on", "rejection_reason",
]);

const alt_doc = {
	// Visa -> Visa Number, Passport -> Passport Number, other -> "<Type> Number"
	set_card_number_label(frm) {
		const t = frm.doc.document_type;
		frm.set_df_property("card_number", "label", t ? __("{0} Number", [__(t)]) : __("Card Number"));
	},

	snapshot_of(frm) {
		const values = {};
		(frm.meta.fields || []).forEach((df) => {
			if (frappe.model.no_value_type.includes(df.fieldtype)) return;
			if (ALT_DOC_SYSTEM_FIELDS.has(df.fieldname)) return;
			const v = frm.doc[df.fieldname];
			values[df.fieldname] = v === undefined || v === null ? "" : String(v);
		});
		return JSON.stringify(values);
	},

	take_snapshot(frm) {
		frm.__alt_doc_snapshot = frm.is_new() ? null : alt_doc.snapshot_of(frm);
	},

	is_own_document(frm) {
		return frm.doc.submitted_by === frappe.session.user;
	},

	show_status_intro(frm) {
		frm.set_intro("");
		const status = frm.doc.approval_status;
		if (status === ALT_DOC_STATUS.PENDING) {
			frm.set_intro(alt_doc.is_own_document(frm)
				? __("Waiting for HR Manager approval.")
				: __("This document is waiting for approval."), "orange");
		} else if (status === ALT_DOC_STATUS.REJECTED) {
			frm.set_intro(__("Rejected: {0}", [frappe.utils.escape_html(frm.doc.rejection_reason || "")]) +
				"<br>" + __("Correct the details and save to resubmit for approval."), "red");
		}
	},

	add_review_buttons(frm) {
		if (frm.is_new() || frm.doc.approval_status !== ALT_DOC_STATUS.PENDING) return;
		if (!frappe.user.has_role("HR Manager") || alt_doc.is_own_document(frm)) return;

		const group = __("Review");
		frm.add_custom_button(__("Approve"), () => alt_doc.run_review(frm, "approve"), group);
		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for rejection"), reqd: 1 },
				(values) => alt_doc.run_review(frm, "reject", { reason: values.reason }),
				__("Reject Document"), __("Reject"));
		}, group);
	},

	run_review(frm, method, args) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Please save or discard your changes first."));
			return;
		}
		frm.call({ method, doc: frm.doc, args, freeze: true }).then(() => {
			frappe.show_alert({
				message: method === "approve" ? __("Document approved") : __("Document rejected"),
				indicator: method === "approve" ? "green" : "red",
			});
			frm.reload_doc();
		});
	},
};

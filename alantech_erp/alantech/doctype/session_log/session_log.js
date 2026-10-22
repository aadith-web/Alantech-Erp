// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

const ALT_SESSION_LOG_API = "alantech_erp.alantech.doctype.session_log.approval";

frappe.ui.form.on("Session Log", {
	async refresh(frm) {
		if (frm.is_new()) return;
		const settings = await frappe.xcall(
			"alantech_erp.alantech.doctype.session_log_settings.session_log_settings.get_session_log_settings"
		);
		const is_hr = frappe.user.has_role("HR Manager") || frappe.user.has_role("HR User");
		const is_approver = frappe.user.has_role(settings.approver_role) || frappe.session.user === "Administrator";
		const status = frm.doc.status;

		// Processed + locked: read-only form
		if (status === "Processed" && settings.lock_after_processing) {
			frm.disable_save();
			frm.set_read_only();
			frm.dashboard.set_headline(__("Processed and locked. Use Reopen to change it."), "blue");
		}

		if (is_hr && ["Draft", "Pending Approval"].includes(status)) {
			frm.add_custom_button(__("Recalculate"), () =>
				frm.call("recalculate").then(() => frm.reload_doc())
			);
		}
		if (!is_approver) return;

		if (["Draft", "Pending Approval", "Approved"].includes(status)) {
			frm.add_custom_button(
				__("Approve"),
				() =>
					frappe
						.xcall(`${ALT_SESSION_LOG_API}.approve_logs`, { names: [frm.doc.name] })
						.then(() => {
							frappe.show_alert({ message: __("Approval started"), indicator: "blue" });
							setTimeout(() => frm.reload_doc(), 2000);
						}),
				__("Review")
			);
			frm.add_custom_button(
				__("Reject"),
				() =>
					frappe.prompt(
						{ fieldname: "reason", fieldtype: "Small Text", label: __("Remark"), reqd: 1 },
						(v) =>
							frappe
								.xcall(`${ALT_SESSION_LOG_API}.reject_logs`, { names: [frm.doc.name], reason: v.reason })
								.then(() => frm.reload_doc()),
						__("Reject Session Log"),
						__("Reject")
					),
				__("Review")
			);
		}
		if (["Processed", "Rejected"].includes(status)) {
			frm.add_custom_button(__("Reopen"), () =>
				frappe.confirm(
					__("Cancel the linked Attendance and Overtime Log and set this log back to Pending Approval?"),
					() => frappe.xcall(`${ALT_SESSION_LOG_API}.reopen_log`, { name: frm.doc.name }).then(() => frm.reload_doc())
				)
			);
		}
	},
});

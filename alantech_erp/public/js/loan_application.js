// Loan Application — Loan Eligibility on the form (Employee Loan Rules).
//
// 1. Stored result: eligibility_result is a hidden Long Text holding HTML built on the server with
//    every value escaped (alantech_erp.loan_rules.engine.render_results_html); a read-only Long Text
//    would show it as plain text, so it is rendered into the eligibility_result_html field.
// 2. Live preview (LR-06, https://app.clickup.com/t/14yr2e57ghj): on a draft Employee application,
//    a change of applicant / loan product / application date / company calls
//    alantech_erp.loan_rules.api.check_loan_eligibility and shows the pass/fail list in the same
//    place. Nothing is stored: the server check on save (loan_rules/loan_application.py) decides.
// 3. Override Loan Rule is shown only to users holding the matched rule's Override Role (rule
//    allows override), and only while the rule is not met; an override already ticked stays
//    visible, read-only for other users. The server checks the role again on save.

const ALT_LOAN_API = "alantech_erp.loan_rules.api";
const ALT_PREVIEW_TRIGGERS = ["applicant_type", "applicant", "loan_product", "posting_date", "company"];

frappe.ui.form.on("Loan Application", {
	refresh(frm) {
		frm._alt_eligibility = null;
		frm.doc.__eligibility_preview = 0;
		alt_toggle_override(frm); // hidden until the rule's Override Role is known
		alt_render_eligibility_result(frm);
		if (frm.is_new() && alt_is_employee_application(frm)) {
			alt_preview_eligibility(frm);
		} else {
			alt_load_override_permission(frm);
		}
	},
	eligibility_result(frm) {
		alt_render_eligibility_result(frm);
	},
	...Object.fromEntries(
		ALT_PREVIEW_TRIGGERS.map((field) => [field, (frm) => alt_preview_eligibility(frm)])
	),
});

function alt_is_employee_application(frm) {
	return frm.doc.applicant_type === "Employee" && !!frm.doc.applicant;
}

function alt_render_eligibility_result(frm, html) {
	const field = frm.get_field("eligibility_result_html");
	if (!field) return;
	field.$wrapper.html(html ?? (frm.doc.eligibility_result || ""));
}

function alt_set_preview(frm, data) {
	frm._alt_eligibility = data;
	frm.doc.__eligibility_preview = data ? 1 : 0;
	alt_render_eligibility_result(frm, data ? data.html : undefined);
	frm.refresh_field("eligibility_result_section");
	frm.layout.refresh_dependency();
	alt_toggle_override(frm);
}

function alt_preview_eligibility(frm) {
	// submitted applications keep the result of their last check (re-checked on approval)
	if (frm.doc.docstatus !== 0) return;
	if (!alt_is_employee_application(frm)) {
		alt_set_preview(frm, null);
		return;
	}
	// a later change wins over a slower earlier response
	const token = (frm._alt_preview_token = (frm._alt_preview_token || 0) + 1);
	frappe
		.call({
			method: `${ALT_LOAN_API}.check_loan_eligibility`,
			args: {
				employee: frm.doc.applicant,
				loan_product: frm.doc.loan_product || null,
				posting_date: frm.doc.posting_date || null,
				company: frm.doc.company || null,
				loan_application: frm.is_new() ? null : frm.doc.name,
			},
		})
		.then((r) => {
			if (token !== frm._alt_preview_token) return;
			alt_set_preview(frm, r.message || null);
		})
		.catch(() => {
			if (token === frm._alt_preview_token) alt_set_preview(frm, null);
		});
}

function alt_load_override_permission(frm) {
	if (frm.doc.applicant_type !== "Employee" || !frm.doc.loan_rule) {
		alt_toggle_override(frm);
		return;
	}
	frappe
		.call({
			method: `${ALT_LOAN_API}.can_override_loan_rule`,
			args: { loan_rule: frm.doc.loan_rule },
		})
		.then((r) => {
			frm._alt_eligibility = {
				rule: frm.doc.loan_rule,
				can_override: !!r.message,
				eligible: frm.doc.eligibility_status === "Eligible",
			};
			alt_toggle_override(frm);
		});
}

function alt_toggle_override(frm) {
	const info = frm._alt_eligibility;
	const ticked = !!frm.doc.rule_override;
	const can = !!(info && info.rule && info.can_override);
	const needed = !!(info && info.rule && !info.eligible);
	frm.toggle_display("rule_override", ticked || (can && needed));
	frm.set_df_property("rule_override", "read_only", can ? 0 : 1);
}

// Loan Disbursement list (HR-F05-x): shows the Sanctioned loans waiting to be paid out.
// Loaded through doctype_list_js in hooks.py; extends Lending's list settings (status colours).
// A "Sanctioned Loans" toolbar button (with count) and "Add Loan Disbursement" list the submitted
// Loans that are Sanctioned / Partially Disbursed with an amount left to disburse; "Disburse" on a
// row opens the Loan Disbursement made by Lending's make_loan_disbursement for the pending amount,
// the same as Create > Loan Disbursement on the Loan.

(() => {
	const METHOD = "alantech_erp.loan_rules.loan.loans_awaiting_disbursement";
	const MAKE = "lending.loan_management.doctype.loan.loan.make_loan_disbursement";
	const LABEL = __("Sanctioned Loans");
	const settings = (frappe.listview_settings["Loan Disbursement"] =
		frappe.listview_settings["Loan Disbursement"] || {});

	settings.primary_action = () => show_loans();

	const lending_onload = settings.onload;
	settings.onload = function (listview) {
		if (lending_onload) lending_onload.call(this, listview);
		// only users who may create it (Loan: HR Head, Loan Disbursement: Accounts Head)
		if (!frappe.model.can_create("Loan Disbursement")) return;
		listview.alt_loans_button = listview.page.add_inner_button(LABEL, () => show_loans());
		update_count(listview);
		// the list view is kept when you leave it: recount whenever it is shown again
		frappe.router.on("change", () => {
			const route = frappe.get_route();
			if (route[0] === "List" && route[1] === "Loan Disbursement") update_count(listview);
		});
	};

	const lending_refresh = settings.refresh;
	settings.refresh = function (listview) {
		if (lending_refresh) lending_refresh.call(this, listview);
		update_count(listview);
	};

	function update_count(listview) {
		const button = listview.alt_loans_button;
		if (!button) return;
		frappe.call(METHOD).then((r) => {
			button.html(`${LABEL} <span class="badge">${(r.message || []).length}</span>`);
		});
	}

	function show_loans() {
		frappe.call(METHOD).then((r) => {
			const rows = r.message || [];
			const dialog = new frappe.ui.Dialog({
				title: __("Disburse a Sanctioned Loan"),
				size: "extra-large",
				fields: [{ fieldtype: "HTML", fieldname: "list" }],
			});
			dialog.fields_dict.list.$wrapper.html(render(rows));
			dialog.fields_dict.list.$wrapper.on("click", "[data-disburse]", function () {
				const row = rows[cint($(this).attr("data-disburse"))];
				dialog.hide();
				frappe
					.call({
						method: MAKE,
						args: { loan: row.name, disbursement_amount: row.pending_amount, as_dict: 1 },
						freeze: true,
					})
					.then((res) => {
						if (!res.message) return;
						const doc = frappe.model.sync(res.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					});
			});
			dialog.show();
		});
	}

	function render(rows) {
		const note = `<p class="text-muted">${__(
			"Loans that are Sanctioned or Partially Disbursed and still have an amount to pay out. A Loan appears here once it is submitted (sanctioned)."
		)}</p>`;
		if (!rows.length) {
			return `${note}<p><b>${__("No Sanctioned Loan is waiting for disbursement.")}</b></p>`;
		}
		const esc = frappe.utils.escape_html;
		const body = rows
			.map(
				(d, i) => `<tr>
					<td>${frappe.utils.get_form_link("Loan", d.name, true)}<br><span class="text-muted">${__(d.status)}</span></td>
					<td>${esc(d.applicant || "")}<br><span class="text-muted">${esc(d.applicant_name || "")}</span></td>
					<td>${esc(d.loan_product || "")}</td>
					<td class="text-right">${format_currency(d.loan_amount)}</td>
					<td class="text-right">${format_currency(d.disbursed_amount)}</td>
					<td class="text-right"><b>${format_currency(d.pending_amount)}</b></td>
					<td><button class="btn btn-xs btn-primary" data-disburse="${i}">${__("Disburse")}</button></td>
				</tr>`
			)
			.join("");
		return `${note}<table class="table table-bordered">
			<thead><tr>
				<th>${__("Loan")}</th><th>${__("Employee")}</th><th>${__("Loan Product")}</th>
				<th class="text-right">${__("Loan Amount")}</th><th class="text-right">${__("Disbursed")}</th>
				<th class="text-right">${__("To Disburse")}</th><th></th>
			</tr></thead><tbody>${body}</tbody></table>`;
	}
})();

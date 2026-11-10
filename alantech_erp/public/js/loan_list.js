// Loan list (HR-F05-x): a Loan is made only from an Approved Loan Application.
// Loaded through doctype_list_js in hooks.py; extends Lending's Loan list settings (status colours).
// "Add Loan" and an "Approved Applications" toolbar button list the Approved applications that have
// no Loan yet; "Create Loan" on a row opens the Loan made by Lending's create_loan mapper.
// The rule itself is enforced on the server (alantech_erp/loan_rules/loan.py).

(() => {
	const METHOD = "alantech_erp.loan_rules.loan.approved_applications_without_loan";
	const CREATE = "lending.loan_management.doctype.loan_application.loan_application.create_loan";
	const settings = (frappe.listview_settings["Loan"] = frappe.listview_settings["Loan"] || {});

	settings.primary_action = () => show_approved_applications();

	const lending_onload = settings.onload;
	settings.onload = function (listview) {
		if (lending_onload) lending_onload.call(this, listview);
		listview.alt_approved_button = listview.page.add_inner_button(__("Approved Applications"), () =>
			show_approved_applications()
		);
		update_count(listview);
		// the list view is kept when you leave it: recount whenever it is shown again
		frappe.router.on("change", () => {
			const route = frappe.get_route();
			if (route[0] === "List" && route[1] === "Loan") update_count(listview);
		});
	};

	// after every list refresh (a Loan saved / submitted / cancelled updates the list in realtime)
	const lending_refresh = settings.refresh;
	settings.refresh = function (listview) {
		if (lending_refresh) lending_refresh.call(this, listview);
		update_count(listview);
	};

	function update_count(listview) {
		const button = listview.alt_approved_button;
		if (!button) return;
		frappe.call(METHOD).then((r) => {
			const count = (r.message || []).length;
			button.html(`${__("Approved Applications")} <span class="badge">${count}</span>`);
		});
	}

	function show_approved_applications() {
		frappe.call(METHOD).then((r) => {
			const rows = r.message || [];
			const dialog = new frappe.ui.Dialog({
				title: __("Create Loan from an Approved Loan Application"),
				size: "extra-large",
				fields: [{ fieldtype: "HTML", fieldname: "list" }],
			});
			dialog.fields_dict.list.$wrapper.html(render(rows));
			dialog.fields_dict.list.$wrapper.on("click", "[data-create]", function () {
				const name = $(this).attr("data-create");
				dialog.hide();
				frappe.model.open_mapped_doc({ method: CREATE, source_name: name });
			});
			dialog.show();
		});
	}

	function render(rows) {
		const note = `<p class="text-muted">${__(
			"A Loan is created only from an Approved Loan Application. To approve one, open the submitted application, set Status to Approved and click Update."
		)}</p>`;
		if (!rows.length) {
			return `${note}<p><b>${__("No Approved Loan Application is waiting for a Loan.")}</b></p>`;
		}
		const esc = frappe.utils.escape_html;
		const body = rows
			.map(
				(d) => `<tr>
					<td>${frappe.utils.get_form_link("Loan Application", d.name, true)}</td>
					<td>${esc(d.applicant || "")}<br><span class="text-muted">${esc(d.applicant_name || "")}</span></td>
					<td>${esc(d.loan_product || "")}</td>
					<td class="text-right">${format_currency(d.loan_amount)}</td>
					<td>${frappe.datetime.str_to_user(d.posting_date)}</td>
					<td><button class="btn btn-xs btn-primary" data-create="${esc(d.name)}">${__("Create Loan")}</button></td>
				</tr>`
			)
			.join("");
		return `${note}<table class="table table-bordered">
			<thead><tr>
				<th>${__("Loan Application")}</th><th>${__("Employee")}</th><th>${__("Loan Product")}</th>
				<th class="text-right">${__("Loan Amount")}</th><th>${__("Posting Date")}</th><th></th>
			</tr></thead><tbody>${body}</tbody></table>`;
	}
})();

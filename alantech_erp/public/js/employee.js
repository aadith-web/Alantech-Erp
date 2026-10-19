// Documents tab on Employee: lists this employee's Document records and opens a new one for upload.
// Loaded through doctype_js in hooks.py. ERPNext's own Employee script keeps working alongside it.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		alt_employee_docs.render(frm);
	},
});

const alt_employee_docs = {
	STATUS_COLOURS: { "Pending Approval": "orange", Approved: "green", Rejected: "red" },

	render(frm) {
		const field = frm.fields_dict.alt_documents_html;
		if (!field) return;
		const $wrapper = $(field.wrapper).empty();

		if (frm.is_new()) {
			$wrapper.html(`<p class="text-muted">${__("Save the employee before uploading documents.")}</p>`);
			return;
		}

		const $toolbar = $(`
			<div class="flex justify-between align-center" style="margin-bottom: var(--margin-md);">
				<div class="text-muted small alt-doc-count"></div>
				<div>
					<button class="btn btn-default btn-xs alt-doc-refresh">${__("Refresh")}</button>
					<button class="btn btn-primary btn-xs alt-doc-upload" style="margin-left: 6px;">
						${__("Upload Document")}
					</button>
				</div>
			</div>`).appendTo($wrapper);
		const $list = $(`<div class="alt-doc-list"></div>`).appendTo($wrapper);

		if (!frappe.model.can_create("Document")) $toolbar.find(".alt-doc-upload").remove();
		$toolbar.find(".alt-doc-upload").on("click", () =>
			frappe.new_doc("Document", { reference_doctype: "Employee", reference_name: frm.doc.name })
		);
		$toolbar.find(".alt-doc-refresh").on("click", () => alt_employee_docs.load(frm, $list, $toolbar));

		alt_employee_docs.load(frm, $list, $toolbar);
	},

	load(frm, $list, $toolbar) {
		$list.html(`<p class="text-muted">${__("Loading...")}</p>`);
		frappe.db
			.get_list("Document", {
				filters: { reference_doctype: "Employee", reference_name: frm.doc.name },
				fields: ["name", "document_type", "card_number", "issue_date", "expiry_date", "approval_status", "attachment", "submitted_by"],
				order_by: "modified desc",
				limit: 200,
			})
			.then((rows) => {
				$toolbar.find(".alt-doc-count").text(__("{0} document(s)", [rows.length]));
				if (!rows.length) {
					$list.html(`<p class="text-muted">${__("No documents uploaded yet.")}</p>`);
					return;
				}
				$list.html(alt_employee_docs.table(rows));
				$list.find("[data-doc]").on("click", (e) => {
					e.preventDefault();
					frappe.set_route("Form", "Document", $(e.currentTarget).attr("data-doc"));
				});
				$list.find("[data-file]").on("click", (e) => {
					e.preventDefault();
					const $btn = $(e.currentTarget);
					alt_employee_docs.preview($btn.attr("data-file"), $btn.attr("data-title"));
				});
				$list.find("[data-review]").on("click", (e) => {
					e.preventDefault();
					const $btn = $(e.currentTarget);
					alt_employee_docs.review(frm, $list, $toolbar, $btn.attr("data-name"), $btn.attr("data-review"));
				});
			})
			.catch(() => $list.html(`<p class="text-muted">${__("Could not load documents.")}</p>`));
	},

	table(rows) {
		const esc = frappe.utils.escape_html;
		const today = frappe.datetime.get_today();
		const body = rows
			.map((r) => {
				const colour = alt_employee_docs.STATUS_COLOURS[r.approval_status] || "gray";
				const status = r.approval_status
					? `<span class="indicator-pill ${colour}">${__(r.approval_status)}</span>`
					: "";
				let expiry = r.expiry_date ? frappe.datetime.str_to_user(r.expiry_date) : "";
				if (r.expiry_date) {
					const days = frappe.datetime.get_day_diff(r.expiry_date, today);
					if (days < 0) expiry = `<span class="text-danger">${expiry}</span>`;
					else if (days <= 30) expiry = `<span class="text-warning">${expiry}</span>`;
				}
				return `<tr>
					<td><a href="#" data-doc="${esc(r.name)}">${esc(r.name)}</a></td>
					<td>${esc(r.document_type || "")}</td>
					<td>${esc(r.card_number || "")}</td>
					<td>${r.issue_date ? frappe.datetime.str_to_user(r.issue_date) : ""}</td>
					<td>${expiry}</td>
					<td>${status}</td>
					<td>${
						r.attachment
							? `<button class="btn btn-default btn-xs" data-file="${esc(r.attachment)}"
								data-title="${esc((r.document_type || "") + " - " + r.name)}">${__("View")}</button>`
							: `<span class="text-muted">${__("No file")}</span>`
					}</td>
					<td style="white-space:nowrap;">${
						alt_employee_docs.can_review(r)
							? `<button class="btn btn-success btn-xs" data-review="approve" data-name="${esc(r.name)}">${__("Approve")}</button>
							   <button class="btn btn-danger btn-xs" data-review="reject" data-name="${esc(r.name)}"
								style="margin-left:4px;">${__("Reject")}</button>`
							: ""
					}</td>
				</tr>`;
			})
			.join("");
		return `<table class="table table-bordered table-hover" style="margin: 0;">
			<thead><tr>
				<th>${__("Document")}</th><th>${__("Document Type")}</th><th>${__("Number")}</th>
				<th>${__("Issue Date")}</th><th>${__("Expiry Date")}</th><th>${__("Approval Status")}</th><th>${__("File")}</th><th>${__("Action")}</th>
			</tr></thead>
			<tbody>${body}</tbody>
		</table>`;
	},

	// HR Manager may approve/reject pending documents they did not submit themselves
	// (the server checks the same rules again in check_can_review)
	can_review(r) {
		return (
			r.approval_status === "Pending Approval" &&
			frappe.user.has_role("HR Manager") &&
			r.submitted_by !== frappe.session.user
		);
	},

	review(frm, $list, $toolbar, name, action) {
		const run = (reason) =>
			frappe
				.call({
					method: "alantech_erp.alantech.doctype.document.document.review_document",
					args: { name, action, reason },
					freeze: true,
				})
				.then(() => {
					frappe.show_alert({
						message: action === "approve" ? __("Document approved") : __("Document rejected"),
						indicator: action === "approve" ? "green" : "red",
					});
					alt_employee_docs.load(frm, $list, $toolbar);
				});

		if (action === "approve") {
			frappe.confirm(__("Approve document {0}?", [name]), () => run());
		} else {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for rejection"), reqd: 1 },
				(values) => run(values.reason),
				__("Reject Document"),
				__("Reject")
			);
		}
	},

	// Show the attached file: images and PDFs inline, anything else as a download link
	preview(file_url, title) {
		const esc = frappe.utils.escape_html;
		if (!/^(\/files\/|\/private\/files\/|https?:\/\/)/i.test(file_url || "")) {
			frappe.msgprint(__("This attachment cannot be previewed."));
			return;
		}
		const url = encodeURI(file_url);
		const ext = (file_url.split("?")[0].split(".").pop() || "").toLowerCase();
		const is_image = ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"].includes(ext);
		const is_pdf = ext === "pdf";

		let body;
		if (is_image) {
			body = `<div style="text-align:center;"><img src="${url}" alt="${esc(title)}"
				style="max-width:100%; max-height:70vh; border-radius:var(--border-radius);"></div>`;
		} else if (is_pdf) {
			body = `<iframe src="${url}" style="width:100%; height:70vh; border:0;"></iframe>`;
		} else {
			body = `<p>${__("Preview is not available for this file type.")}</p>`;
		}

		const dialog = new frappe.ui.Dialog({
			title: esc(title || __("Document File")),
			size: "large",
			fields: [{ fieldname: "preview", fieldtype: "HTML" }],
			primary_action_label: __("Open in New Tab"),
			primary_action: () => window.open(url, "_blank"),
		});
		dialog.fields_dict.preview.$wrapper.html(
			`${body}<p class="text-muted small" style="margin-top:var(--margin-sm);">
				<a href="${url}" target="_blank" download>${__("Download")}</a> · ${esc(file_url.split("/").pop())}
			</p>`
		);
		dialog.show();
	},
};

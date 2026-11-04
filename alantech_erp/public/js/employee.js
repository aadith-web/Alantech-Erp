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
				fields: ["name", "document_type", "card_number", "issue_date", "expiry_date", "approval_status", "submitted_by"],
				order_by: "modified desc",
				limit: 200,
			})
			.then((rows) =>
				// several files per document (Document Files table)
				frappe
					.xcall("alantech_erp.alantech.doctype.document.document.get_files", {
						names: rows.map((r) => r.name),
					})
					.then((files) => rows.map((r) => ({ ...r, files: files[r.name] || [] })))
			)
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
				$list.find("[data-files]").on("click", (e) => {
					e.preventDefault();
					const row = rows.find((r) => r.name === $(e.currentTarget).attr("data-files"));
					if (row) alt_employee_docs.preview(row.files, `${row.document_type || ""} - ${row.name}`);
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
						r.files.length
							? `<button class="btn btn-default btn-xs" data-files="${esc(r.name)}">${
									r.files.length > 1 ? __("View ({0})", [r.files.length]) : __("View")
								}</button>`
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

	// Show the document's files: images and PDFs inline, anything else as a download link.
	// With several files, a button per file switches between them.
	preview(files, title) {
		const esc = frappe.utils.escape_html;
		const valid = (files || []).filter((f) => /^(\/files\/|\/private\/files\/|https?:\/\/)/i.test(f.file || ""));
		if (!valid.length) {
			frappe.msgprint(__("This attachment cannot be previewed."));
			return;
		}
		let current = valid[0];

		const dialog = new frappe.ui.Dialog({
			title: esc(title || __("Document File")),
			size: "large",
			fields: [{ fieldname: "preview", fieldtype: "HTML" }],
			primary_action_label: __("Open in New Tab"),
			primary_action: () => window.open(encodeURI(current.file), "_blank"),
		});
		const $wrapper = dialog.fields_dict.preview.$wrapper;
		const $switcher = $(`<div style="margin-bottom:var(--margin-sm);"></div>`).appendTo($wrapper);
		const $body = $(`<div></div>`).appendTo($wrapper);
		const label = (f, i) => f.description || __("File {0}", [i + 1]);

		const show = (index) => {
			current = valid[index];
			const url = encodeURI(current.file);
			const ext = (current.file.split("?")[0].split(".").pop() || "").toLowerCase();
			let body;
			if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"].includes(ext)) {
				body = `<div style="text-align:center;"><img src="${url}" alt="${esc(label(current, index))}"
					style="max-width:100%; max-height:70vh; border-radius:var(--border-radius);"></div>`;
			} else if (ext === "pdf") {
				body = `<iframe src="${url}" style="width:100%; height:70vh; border:0;"></iframe>`;
			} else {
				body = `<p>${__("Preview is not available for this file type.")}</p>`;
			}
			$body.html(
				`${body}<p class="text-muted small" style="margin-top:var(--margin-sm);">
					<a href="${url}" target="_blank" download>${__("Download")}</a> · ${esc(current.file.split("/").pop())}
				</p>`
			);
			$switcher.find("button").each((i, btn) => $(btn).toggleClass("btn-primary", i === index));
		};

		if (valid.length > 1) {
			valid.forEach((f, i) => {
				$(`<button class="btn btn-default btn-xs" style="margin:0 4px 4px 0;">${esc(label(f, i))}</button>`)
					.on("click", () => show(i))
					.appendTo($switcher);
			});
		}
		show(0);
		dialog.show();
	},
};

// Assets: Issue / Receive buttons, and a warning on leaving employees who still hold assets.
frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || !frappe.model.can_read("Employee Asset Handover")) return;
		const handover = "Employee Asset Handover";

		if (frappe.model.can_create(handover)) {
			if (frm.doc.status === "Active") {
				frm.add_custom_button(__("Issue Asset"), () =>
					frappe.new_doc(handover, { transaction_type: "Issue", employee: frm.doc.name }), __("Assets"));
			}
			frm.add_custom_button(__("Receive Assets"), () =>
				frappe.new_doc(handover, { transaction_type: "Receipt", employee: frm.doc.name }), __("Assets"));
		}
		frm.add_custom_button(__("Handover History"), () =>
			frappe.set_route("List", handover, { employee: frm.doc.name }), __("Assets"));

		const leaving = frm.doc.status === "Left" || frm.doc.relieving_date || frm.doc.resignation_letter_date;
		if (!leaving) return;
		frappe
			.call({
				method: "alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover.get_employee_assets",
				args: { employee: frm.doc.name },
			})
			.then(({ message: assets = [] }) => {
				if (!assets.length) return;
				const names = assets.map((a) => frappe.utils.escape_html(a.asset_name || a.asset)).join(", ");
				frm.dashboard.set_headline_alert(
					__("Assets not returned ({0}): {1}", [assets.length, names]),
					"orange"
				);
			});
	},
});

// Mobile: pick the country, then type the number (Phone field). Checked against the country code
// as soon as it is entered; the same check runs again on save (employee_validation.validate_mobile_number).
frappe.ui.form.on("Employee", {
	onload(frm) {
		frm.set_df_property("cell_number", "description", __("Select the country code, then enter the number"));
	},
	cell_number(frm) {
		// The Phone field sets the typed digits first and adds the country code ("+91-...") right
		// after: only the value with the code is checked (a number left without one fails on save)
		const mobile = frm.doc.cell_number || "";
		const field = frm.fields_dict.cell_number;
		const show = (error) => {
			field.df.invalid = !!error;
			field.set_invalid();
			field.set_description(
				error
					? `<span class="text-danger">${error}</span>`
					: __("Select the country code, then enter the number")
			);
		};
		if (!mobile.startsWith("+")) {
			if (!mobile) show(null);
			return;
		}
		frappe
			.xcall("alantech_erp.setup.employee_validation.check_mobile_number", { mobile })
			.then((error) => frm.doc.cell_number === mobile && show(error));
	},
});

// New employee: fields needed to create it, marked mandatory. The server checks the same list
// (employee_validation.REQUIRED_ON_CREATE); existing employees are not affected.
// Department and Reports To are filled from the designation as soon as it is picked.
const ALT_EMPLOYEE_REQUIRED = [
	"first_name", "gender", "date_of_birth", "date_of_joining", "company", "status",
	"department", "designation", "branch", "reports_to", "employment_type", "cell_number",
	"default_shift",
];
const ALT_TOP_DESIGNATION = "Managing Director"; // reports to no one (org_structure.TOP_DESIGNATION)

frappe.ui.form.on("Employee", {
	setup() {
		alt_employee_required.merge_email_in_missing_fields();
	},
	refresh(frm) {
		alt_employee_required.toggle(frm);
	},
	designation(frm) {
		alt_employee_required.toggle(frm);
		alt_employee_required.fill_from_designation(frm);
	},
	company(frm) {
		alt_employee_required.fill_from_designation(frm);
	},
	company_email(frm) {
		alt_employee_required.toggle_email(frm);
	},
	personal_email(frm) {
		alt_employee_required.toggle_email(frm);
	},
});

const alt_employee_required = {
	toggle(frm) {
		const is_new = frm.is_new();
		ALT_EMPLOYEE_REQUIRED.forEach((field) => frm.toggle_reqd(field, is_new));
		if (is_new && frm.doc.designation === ALT_TOP_DESIGNATION) frm.toggle_reqd("reports_to", false);
		const hint = is_new ? __("Company Email or Personal Email is required.") : "";
		["company_email", "personal_email"].forEach((field) => frm.set_df_property(field, "description", hint));
		alt_employee_required.toggle_email(frm);
	},

	// One email is enough: both are mandatory while both are empty, so Frappe's own check on save
	// lists them with the other missing fields ("Company Email is required.")
	toggle_email(frm) {
		const fields = ["company_email", "personal_email"];
		const none = frm.is_new() && fields.every((field) => !(frm.doc[field] || "").trim());
		fields.forEach((field) => frm.toggle_reqd(field, none));
	},

	// On save, Frappe's "Missing Fields" list shows one line for the two emails:
	// "Company Email or Personal Email is required." (labels are put back right after the check)
	merge_email_in_missing_fields() {
		const check_mandatory = frappe.ui.form.check_mandatory;
		if (check_mandatory.__alt_employee_email) return;
		frappe.ui.form.check_mandatory = function (frm) {
			// the field copies check_mandatory reads (same ones frm.toggle_reqd changes)
			const get = (field) => frappe.meta.get_docfield("Employee", field, frm.docname);
			const company = frm.doctype === "Employee" && get("company_email");
			const personal = company && get("personal_email");
			if (!personal || !company.reqd) return check_mandatory.apply(this, arguments);
			const label = company.label;
			company.label = __("Company Email or Personal Email");
			personal.reqd = 0;
			try {
				return check_mandatory.apply(this, arguments);
			} finally {
				company.label = label;
				alt_employee_required.toggle_email(frm);
				frm.refresh_field("company_email");
			}
		};
		frappe.ui.form.check_mandatory.__alt_employee_email = true;
	},

	// same defaults the server fills on save (org_structure.apply_designation_defaults)
	fill_from_designation(frm) {
		const { designation, company } = frm.doc;
		if (!frm.is_new() || !designation || (frm.doc.department && frm.doc.reports_to)) return;
		frappe
			.xcall("alantech_erp.org_structure.designation_defaults", { designation, company })
			.then((r) => {
				if (frm.doc.designation !== designation) return;
				if (!frm.doc.department && r.department) frm.set_value("department", r.department);
				if (!frm.doc.reports_to && r.reports_to) frm.set_value("reports_to", r.reports_to);
			});
	},
};

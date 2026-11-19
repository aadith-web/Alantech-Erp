// Documents tab on Employee: lists this employee's Document records and opens a new one for upload.
// Loaded through doctype_js in hooks.py. ERPNext's own Employee script keeps working alongside it.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		alt_employee_docs.render(frm);
		alt_notice_period.render(frm);

		// Company Policy card on Connections: open the policy list
		if (!frm.is_new()) {
			setTimeout(() => {
				frm.dashboard.wrapper
					.find('.document-link[data-doctype="Company Policy"]')
					.off("click")
					.on("click", (e) => {
						e.preventDefault();
						e.stopPropagation();
						frappe.set_route("List", "Company Policy");
					});
			}, 500);
		}
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
		$toolbar.find(".alt-doc-upload").on("click", () => alt_employee_docs.upload(frm));
		$toolbar.find(".alt-doc-refresh").on("click", () => alt_employee_docs.load(frm, $list, $toolbar));

		alt_employee_docs.load(frm, $list, $toolbar);
	},

	upload(frm, document_type) {
		frappe.new_doc("Document", {
			reference_doctype: "Employee",
			reference_name: frm.doc.name,
			...(document_type ? { document_type } : {}),
		});
	},

	// One table: the mandatory document types first (Document Type Master > Mandatory at Joining,
	// ClickUp 14yr2e57mhp) with their documents, or a "Missing" row with Upload; then the other
	// uploaded documents.
	load(frm, $list, $toolbar) {
		$list.html(`<p class="text-muted">${__("Loading...")}</p>`);
		const documents = frappe.db
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
			);
		const mandatory = frappe
			.xcall("alantech_erp.alantech.doctype.document.document.get_mandatory_documents", {
				employee: frm.doc.name,
			})
			.catch(() => []);

		Promise.all([documents, mandatory])
			.then(([rows, required]) => {
				required = required || [];
				$toolbar.find(".alt-doc-count").html(alt_employee_docs.summary(rows, required));
				if (!rows.length && !required.length) {
					$list.html(`<p class="text-muted">${__("No documents uploaded yet.")}</p>`);
					return;
				}
				$list.html(alt_employee_docs.table(alt_employee_docs.combine(rows, required)));
				$list.find("[data-doc]").on("click", (e) => {
					e.preventDefault();
					frappe.set_route("Form", "Document", $(e.currentTarget).attr("data-doc"));
				});
				$list.find("[data-files]").on("click", (e) => {
					e.preventDefault();
					const row = rows.find((r) => r.name === $(e.currentTarget).attr("data-files"));
					if (row) alt_employee_docs.preview(row.files, `${row.document_type || ""} - ${row.name}`);
				});
				$list.find("[data-upload]").on("click", (e) => {
					e.preventDefault();
					alt_employee_docs.upload(frm, $(e.currentTarget).attr("data-upload"));
				});
				$list.find("[data-review]").on("click", (e) => {
					e.preventDefault();
					const $btn = $(e.currentTarget);
					alt_employee_docs.review(frm, $list, $toolbar, $btn.attr("data-name"), $btn.attr("data-review"));
				});
			})
			.catch(() => $list.html(`<p class="text-muted">${__("Could not load documents.")}</p>`));
	},

	summary(rows, required) {
		const count = __("{0} document(s)", [rows.length]);
		if (!required.length) return count;
		const done = required.filter((r) => ["Approved", "Pending Approval"].includes(r.status)).length;
		const colour = done === required.length ? "text-success" : "text-danger";
		return `${count} · <span class="${colour}" style="font-weight:600;">${__(
			"Mandatory documents: {0} of {1} uploaded",
			[done, required.length]
		)}</span>`;
	},

	// Table rows: each mandatory type's documents (or one Missing row), then the other documents.
	// A rejected mandatory type also gets an Upload button.
	combine(rows, required) {
		const out = [];
		const shown = new Set();
		required.forEach((req) => {
			const docs = rows.filter((r) => r.document_type === req.document_type);
			const reupload = req.status === "Rejected";
			if (!docs.length) {
				out.push({ document_type: req.document_type, mandatory: true, missing: true });
				return;
			}
			docs.forEach((d, i) => {
				shown.add(d.name);
				out.push({ ...d, mandatory: true, reupload: reupload && i === 0 });
			});
		});
		rows.filter((r) => !shown.has(r.name)).forEach((r) => out.push(r));
		return out;
	},

	table(rows) {
		const esc = frappe.utils.escape_html;
		const today = frappe.datetime.get_today();
		const can_upload = frappe.model.can_create("Document");
		const upload_btn = (type) =>
			can_upload
				? `<button class="btn btn-primary btn-xs" data-upload="${esc(type)}">${__("Upload")}</button>`
				: "";
		const body = rows
			.map((r) => {
				const type = `${esc(r.document_type || "")}${
					r.mandatory ? ` <span class="text-danger" title="${__("Mandatory")}">*</span>` : ""
				}`;
				if (r.missing) {
					return `<tr>
						<td>${type}</td><td></td><td></td><td></td><td></td>
						<td><span class="indicator-pill red">${__("Missing")}</span></td>
						<td><span class="text-muted">${__("No file")}</span></td>
						<td style="white-space:nowrap;">${upload_btn(r.document_type)}</td>
					</tr>`;
				}
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
				const review = alt_employee_docs.can_review(r)
					? `<button class="btn btn-success btn-xs" data-review="approve" data-name="${esc(r.name)}">${__("Approve")}</button>
						<button class="btn btn-danger btn-xs" data-review="reject" data-name="${esc(r.name)}"
							style="margin-left:4px;">${__("Reject")}</button>`
					: "";
				return `<tr>
					<td>${type}</td>
					<td><a href="#" data-doc="${esc(r.name)}">${esc(r.name)}</a></td>
					<td>${esc(r.card_number || "")}</td>
					<td>${r.issue_date ? frappe.datetime.str_to_user(r.issue_date) : ""}</td>
					<td>${expiry}</td>
					<td>${status}</td>
					<td>${r.files.length
						? `<button class="btn btn-default btn-xs" data-files="${esc(r.name)}">${r.files.length > 1 ? __("View ({0})", [r.files.length]) : __("View")
						}</button>`
						: `<span class="text-muted">${__("No file")}</span>`
					}</td>
					<td style="white-space:nowrap;">${review}${r.reupload ? upload_btn(r.document_type) : ""}</td>
				</tr>`;
			})
			.join("");
		return `<table class="table table-bordered table-hover" style="margin: 0;">
			<thead><tr>
				<th>${__("Document Type")}</th><th>${__("Document")}</th><th>${__("Number")}</th>
				<th>${__("Issue Date")}</th><th>${__("Expiry Date")}</th><th>${__("Status")}</th>
				<th>${__("File")}</th><th>${__("Action")}</th>
			</tr></thead>
			<tbody>${body}</tbody>
		</table>
		<p class="text-muted small" style="margin-top: var(--margin-xs);">${__("* Mandatory at joining")}</p>`;
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
	"default_shift", "grade",
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

// Fields needed before the first payroll (ClickUp 14yr2e57mhp): listed at the top of a saved,
// active employee until filled. Salary Structure Assignment / Payroll Entry are refused without
// them (setup/employee_payroll_fields.py, which also decides the list).
frappe.ui.form.on("Employee", {
	refresh(frm) {
		frm.set_intro("");
		if (frm.is_new() || frm.doc.status !== "Active") return;
		frappe
			.xcall("alantech_erp.setup.employee_payroll_fields.get_missing_payroll_fields", {
				employee: frm.doc.name,
			})
			.then((missing) => {
				if (!missing || !missing.length || frm.doc.__unsaved) return;
				const fields = missing.map((label) => frappe.utils.escape_html(label)).join(", ");
				frm.set_intro(__("Needed before the first payroll: {0}", [fields]), "orange");
			});
	},
});

// Nationality (Citizen) is mandatory on new and existing employees (ClickUp 14yr2e57r7h). The
// server refuses a new employee without it and never lets it be cleared
// (setup/employee_nationality.py); older employees are asked for it on their next edit here.
frappe.ui.form.on("Employee", {
	refresh(frm) {
		frm.toggle_reqd("alt_nationality", true);
	},
});

// Minimum age: 18 on the Date of Joining (today when blank). Shown under Date of Birth as soon as
// either date is entered; the save is refused by employee_validation.validate_minimum_age.
const ALT_MINIMUM_AGE = 18;
frappe.ui.form.on("Employee", {
	date_of_birth: (frm) => alt_check_minimum_age(frm),
	date_of_joining: (frm) => alt_check_minimum_age(frm),
});

function alt_check_minimum_age(frm) {
	const { date_of_birth: dob, date_of_joining: doj } = frm.doc;
	let note = "";
	if (dob) {
		const on = doj || frappe.datetime.get_today();
		const age = Math.max(moment(on).diff(moment(dob), "years"), 0);
		if (age < ALT_MINIMUM_AGE) {
			note = `<span class="text-danger">${__(
				"Must be at least {0} years old on the Date of Joining (now {1}).",
				[ALT_MINIMUM_AGE, age]
			)}</span>`;
		}
	}
	frm.set_df_property("date_of_birth", "description", note);
}

// PAN Number in capitals while typing (ClickUp 14yr2e57r7k); the server upper-cases it too
// (employee_nationality.validate_indian_ids).
frappe.ui.form.on("Employee", {
	refresh(frm) {
		const $input = frm.get_field("pan_number")?.$input;
		if (!$input || $input.data("alt-uppercase")) return;
		$input.data("alt-uppercase", true);
		$input.css("text-transform", "uppercase");
		$input.on("input", function () {
			const upper = this.value.toUpperCase();
			if (this.value === upper) return;
			const { selectionStart: start, selectionEnd: end } = this;
			this.value = upper;
			this.setSelectionRange(start, end);
		});
	},
	pan_number(frm) {
		const upper = (frm.doc.pan_number || "").toUpperCase();
		if (frm.doc.pan_number && frm.doc.pan_number !== upper) frm.set_value("pan_number", upper);
	},
});

// Aadhaar Number in groups of four while typing ("2345 6789 0124"), the way it is stored on the
// Employee and the Aadhaar documents (employee_nationality.format_aadhaar).
function alt_format_aadhaar(value) {
	const digits = (value || "").replace(/\D/g, "").slice(0, 12);
	return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

frappe.ui.form.on("Employee", {
	refresh(frm) {
		const $input = frm.get_field("alt_aadhaar_number")?.$input;
		if (!$input || $input.data("alt-aadhaar")) return;
		$input.data("alt-aadhaar", true);
		$input.attr("inputmode", "numeric");
		$input.on("input", function () {
			const formatted = alt_format_aadhaar(this.value);
			if (this.value === formatted) return;
			// keep the cursor after the same number of digits
			const digits_before = this.value.slice(0, this.selectionStart).replace(/\D/g, "").length;
			this.value = formatted;
			let pos = 0;
			for (let seen = 0; pos < formatted.length && seen < digits_before; pos++) {
				if (/\d/.test(formatted[pos])) seen++;
			}
			this.setSelectionRange(pos, pos);
		});
	},
	alt_aadhaar_number(frm) {
		const value = frm.doc.alt_aadhaar_number || "";
		const formatted = alt_format_aadhaar(value);
		if (value && /^\d{12}$/.test(value.replace(/\D/g, "")) && formatted !== value) {
			frm.set_value("alt_aadhaar_number", formatted);
		}
	},
});

// Notice Period tab (ClickUp 14yr2e57r71): the employee's Employee Notice Period, created with the
// employee (company policy default, HR Settings > Default Notice Period (Days)).
const alt_notice_period = {
	render(frm) {
		const field = frm.fields_dict.alt_notice_period_html;
		if (!field) return;
		const $wrapper = $(field.wrapper).empty();
		if (frm.is_new()) {
			$wrapper.html(
				`<p class="text-muted">${__(
					"The notice period is created when the employee is saved (company policy: HR Settings > Default Notice Period)."
				)}</p>`
			);
			return;
		}
		frappe
			.xcall(
				"alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period.get_notice_period",
				{ employee: frm.doc.name }
			)
			.then((r) => {
				if (!r) {
					$wrapper.html(`<p class="text-muted">${__("No notice period yet. Save the employee to create it.")}</p>`);
					return;
				}
				const esc = frappe.utils.escape_html;
				const row = (label, value) => `
					<div class="col-sm-4" style="margin-bottom: var(--margin-md);">
						<div class="text-muted small">${label}</div>
						<div class="bold">${value}</div>
					</div>`;
				const can_edit = frappe.model.can_write("Employee Notice Period");
				$wrapper.html(`
					<div class="row">
						${row(__("Notice Days"), __("{0} days", [r.notice_days]))}
						${row(__("Effective From"), r.effective_from ? frappe.datetime.str_to_user(r.effective_from) : "-")}
						${row(__("Source"), esc(__(r.source || "")))}
					</div>
					${r.remarks ? `<p class="text-muted">${esc(r.remarks)}</p>` : ""}
					${
						// HR only: an employee just reads the details here (their record is read-only)
						can_edit
							? `<button class="btn btn-default btn-xs alt-notice-open">${__("Edit Notice Period")}</button>`
							: ""
					}`);
				$wrapper
					.find(".alt-notice-open")
					.on("click", () => frappe.set_route("Form", "Employee Notice Period", r.name));
			});
	},
};

// Reports To lists managers only (ClickUp 14yr2e57t0m): employees whose user has a Manager role or
// Leave Approver (setup/reports_to.py, which also checks it on save). Replaces ERPNext's query.
frappe.ui.form.on("Employee", {
	refresh(frm) {
		frm.set_query("reports_to", () => ({
			query: "alantech_erp.setup.reports_to.reports_to_query",
			filters: [
				["status", "=", "Active"],
				["name", "!=", frm.doc.name],
			],
		}));
		frm.set_df_property(
			"reports_to",
			"description",
			__("Managers only: employees whose user has a Manager role or Leave Approver.")
		);
	},
});

// Salary: "Create Salary Structure" without an active Salary Structure Assignment, "View Salary
// Structure" with one (ClickUp 14yr2e586v5, setup/salary_structure_button.py). Checked again on
// every refresh, when the form is shown again, and when an assignment of this employee is
// submitted or cancelled. The popups behind the buttons come with ClickUp 14yr2e586v6 / v8; until
// then Create opens a new assignment filled from the grade and View opens the active one.
const ALT_SALARY_BUTTONS = [__("Create Salary Structure"), __("View Salary Structure")];
const ALT_SALARY_EVENT = "alt_salary_structure_assignment_changed";

function alt_salary_button(frm) {
	if (frm.is_new()) return;
	const token = (frm._alt_salary_token = (frm._alt_salary_token || 0) + 1);
	frappe
		.xcall("alantech_erp.setup.salary_structure_button.get_salary_structure_button", {
			employee: frm.doc.name,
		})
		.then((state) => {
			if (token !== frm._alt_salary_token || !state) return; // a newer check is running
			ALT_SALARY_BUTTONS.forEach((label) => frm.remove_custom_button(label));
			if (state.action === "view") {
				frm.add_custom_button(ALT_SALARY_BUTTONS[1], () =>
					frappe.set_route("Form", "Salary Structure Assignment", state.assignment.name)
				);
			} else if (state.action === "create") {
				frm.add_custom_button(ALT_SALARY_BUTTONS[0], () =>
					frappe.new_doc("Salary Structure Assignment", state.new_assignment)
				);
			}
		});
}

frappe.ui.form.on("Employee", {
	setup(frm) {
		frappe.realtime.on(ALT_SALARY_EVENT, ({ employee } = {}) => {
			if (employee && employee === frm.doc?.name) alt_salary_button(frm);
		});
		// back on the form after creating the assignment elsewhere
		// (frappe.container triggers "show" on the form's own page, frm.wrapper)
		$(frm.wrapper).on("show", () => frm.doc && alt_salary_button(frm));
	},
	refresh(frm) {
		alt_salary_button(frm);
	},
});

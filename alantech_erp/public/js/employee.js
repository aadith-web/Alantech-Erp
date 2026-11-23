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
				fields: ["name", "document_type", "card_number", "issue_date", "expiry_date", "approval_status", "submitted_by",
					"modified"],
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

		// expiring soon / expired (ClickUp 14yr2e58g46, document_expiry_warning.py)
		const warnings = frappe
			.xcall("alantech_erp.alantech.doctype.document.document_expiry_warning.get_expiry_warnings", {
				reference_doctype: "Employee",
				reference_name: frm.doc.name,
			})
			.catch(() => []);

		Promise.all([documents, mandatory, warnings])
			.then(([rows, required, warned]) => {
				required = required || [];
				const by_name = {};
				(warned || []).forEach((w) => (by_name[w.name] = w));
				rows.forEach((r) => (r.expiry_warning = by_name[r.name] || null));
				$toolbar.find(".alt-doc-count").html(alt_employee_docs.summary(rows, required));
				if (!rows.length && !required.length) {
					$list.html(`<p class="text-muted">${__("No documents uploaded yet.")}</p>`);
					return;
				}
				$list.html(
					alt_employee_docs.expiry_banner(warned || []) +
					alt_employee_docs.table(alt_employee_docs.combine(rows, required))
				);
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

	expiry_banner(warned) {
		if (!warned.length) return "";
		const esc = frappe.utils.escape_html;
		const expired = warned.some((w) => w.status === "expired");
		const items = warned
			.map((w) => `<li><a href="#" data-doc="${esc(w.name)}">${esc(w.message)}</a></li>`)
			.join("");
		return `<div class="form-message ${expired ? "red" : "yellow"}"
			style="margin-bottom: var(--margin-sm); border-radius: var(--border-radius);">
			<ul style="margin:0; padding-left:18px;">${items}</ul></div>`;
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
		// Edit: opens the document's form (same rules there: an employee's edit goes back for approval)
		const edit_btn = (name) =>
			frappe.model.can_write("Document")
				? `<button class="btn btn-default btn-xs" data-doc="${esc(name)}" style="margin-right:4px;">${__("Edit")}</button>`
				: "";
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
						<td><span class="indicator-pill red" style="white-space:nowrap;">${__("Missing")}</span></td>
						<td></td>
						<td><span class="text-muted">${__("No file")}</span></td>
						<td style="white-space:nowrap;">${upload_btn(r.document_type)}</td>
					</tr>`;
				}
				const colour = alt_employee_docs.STATUS_COLOURS[r.approval_status] || "gray";
				const status = r.approval_status
					? `<span class="indicator-pill ${colour}" style="white-space:nowrap;">${__(r.approval_status)}</span>`
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
					<td title="${r.modified ? esc(frappe.datetime.str_to_user(r.modified)) : ""}">${
						r.modified ? frappe.datetime.str_to_user(r.modified, false, true) : ""}</td>
					<td>${r.files.length
						? `<button class="btn btn-default btn-xs" data-files="${esc(r.name)}">${r.files.length > 1 ? __("View ({0})", [r.files.length]) : __("View")
						}</button>`
						: `<span class="text-muted">${__("No file")}</span>`
					}</td>
					<td style="white-space:nowrap;">${edit_btn(r.name)}${review}${r.reupload ? upload_btn(r.document_type) : ""}</td>
				</tr>`;
			})
			.join("");
		return `<table class="table table-bordered table-hover" style="margin: 0;">
			<thead><tr>
				<th>${__("Document Type")}</th><th>${__("Document")}</th><th>${__("Number")}</th>
				<th>${__("Issue Date")}</th><th>${__("Expiry Date")}</th><th>${__("Status")}</th>
				<th>${__("Last Updated")}</th><th>${__("File")}</th><th>${__("Action")}</th>
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
		alt_employee_required.fill_from_designation(frm, true);
	},
	company(frm) {
		alt_employee_required.fill_from_designation(frm, false);
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

	// Department and Reports To from the designation (org_structure.designation_defaults, the same
	// ones the server fills on save). On a Designation change (ClickUp 14yr2e58fq1) they follow the
	// new designation, also when already filled and on saved employees: Reports To is the new
	// designation's manager (none for the Managing Director). A value the form itself filled from
	// the previous designation is cleared when the new one has no rule; one typed by hand is kept
	// then. On a Company change only empty fields are filled.
	fill_from_designation(frm, designation_changed) {
		const { designation, company } = frm.doc;
		if (!designation) return;
		if (!designation_changed && (!frm.is_new() || (frm.doc.department && frm.doc.reports_to))) return;
		const auto = (frm._alt_auto_from_designation ||= {});
		frappe
			.xcall("alantech_erp.org_structure.designation_defaults", {
				designation,
				company,
				employee: frm.is_new() ? null : frm.doc.name,
			})
			.then((r) => {
				if (frm.doc.designation !== designation) return; // changed again meanwhile
				// `always`: a new rule replaces even a value typed by hand (Reports To, per the
				// task); otherwise only an empty field or one this form filled is replaced.
				const apply = (field, value, always) => {
					const current = frm.doc[field] || null;
					const ours = Boolean(current) && current === auto[field];
					let next = current;
					if (value && (!current || ours || (designation_changed && always))) next = value;
					else if (!value && designation_changed && ours) next = null;
					if (next === current) return;
					auto[field] = next;
					frm.set_value(field, next);
				};
				apply("department", r.department, false);
				apply("reports_to", r.is_top ? null : r.reports_to, true);
				// promoted to Managing Director: reports to no one, also when typed by hand
				if (designation_changed && r.is_top && frm.doc.reports_to) frm.set_value("reports_to", null);
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
// submitted or cancelled. Create and View open the popups below (ClickUp 14yr2e586v6 / v8).
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
				frm.add_custom_button(ALT_SALARY_BUTTONS[1], () => alt_view_salary_structure(frm));
			} else if (state.action === "create") {
				frm.add_custom_button(ALT_SALARY_BUTTONS[0], () => alt_create_salary_structure(frm));
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

// Create Salary Structure popup (ClickUp 14yr2e586v6, setup/salary_structure_popup.py): Grade (the
// employee's, or chosen and saved when blank), Sub Band of that grade, Gross Amount from the grade's
// sub band row, From Date. Creates the Salary Structure Assignment (Base = Gross Amount, the grade's
// Default Salary Structure), submitted unless "Submit" is unticked.
// Cost Centers table (ClickUp 14yr2e589er): the salary cost split across cost centers, total 100%,
// copied to the assignment's Cost Centers (payroll_cost_centers), which payroll splits the cost by.
function alt_create_salary_structure(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the employee first."));
		return;
	}
	const method = "alantech_erp.setup.salary_structure_popup.";
	let grade_details = { sub_bands: [] };

	const dialog = new frappe.ui.Dialog({
		title: __("Create Salary Structure"),
		fields: [
			{
				fieldname: "grade",
				fieldtype: "Link",
				options: "Employee Grade",
				label: __("Grade"),
				reqd: 1,
				default: frm.doc.grade,
				read_only: frm.doc.grade ? 1 : 0,
				description: frm.doc.grade ? "" : __("Saved to the employee."),
				onchange: () => load_grade(),
			},
			{
				fieldname: "sub_band",
				fieldtype: "Link",
				options: "Sub Band",
				label: __("Sub Band"),
				reqd: 1,
				get_query: () => ({
					filters: { name: ["in", grade_details.sub_bands.map((r) => r.sub_band)] },
				}),
				onchange: () => set_gross(),
			},
			{ fieldname: "gross_amount", fieldtype: "Currency", label: __("Gross Amount"), read_only: 1 },
			{ fieldtype: "Column Break" },
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
				onchange: () => alt_show_income_tax_slab(dialog, frm.doc.company),
			},
			alt_employment_state_field(),
			alt_income_tax_slab_field(),
			{ fieldname: "salary_structure", fieldtype: "Data", label: __("Salary Structure"), read_only: 1 },
			{
				fieldname: "submit",
				fieldtype: "Check",
				label: __("Submit"),
				default: 1,
				description: __("Untick to keep the assignment as a draft."),
			},
			...alt_cost_center_fields(
				frm,
				frm.doc.payroll_cost_center ? [{ cost_center: frm.doc.payroll_cost_center, percentage: 100 }] : [],
				() => dialog
			),
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			const cost_centers = alt_cost_center_rows(dialog);
			if (!alt_cost_centers_ok(cost_centers)) return;
			dialog.disable_primary_action();
			frappe
				.xcall(method + "create_salary_structure_assignment", {
					cost_centers,
					employee: frm.doc.name,
					grade: values.grade,
					sub_band: values.sub_band,
					from_date: values.from_date,
					employment_state: values.employment_state,
					submit: values.submit ? 1 : 0,
				})
				.then((r) => {
					dialog.hide();
					frappe.show_alert({
						message: __("Salary Structure Assignment {0} {1}", [
							`<a href="/app/salary-structure-assignment/${encodeURIComponent(r.name)}">${frappe.utils.escape_html(r.name)}</a>`,
							r.docstatus === 1 ? __("submitted") : __("saved as draft"),
						]),
						indicator: "green",
					});
					frm.reload_doc(); // grade may be new; refresh also re-checks the button
				})
				.finally(() => dialog.enable_primary_action());
		},
	});

	function set_gross() {
		const sub_band = dialog.get_value("sub_band");
		const row = grade_details.sub_bands.find((r) => r.sub_band === sub_band);
		dialog.set_value("gross_amount", row ? row.gross_amount : null);
	}

	function load_grade() {
		const grade = dialog.get_value("grade");
		grade_details = { sub_bands: [] };
		dialog.set_value("sub_band", null);
		dialog.set_value("gross_amount", null);
		dialog.set_value("salary_structure", null);
		if (!grade) return;
		frappe.xcall(method + "get_grade_details", { grade }).then((details) => {
			if (dialog.get_value("grade") !== grade) return; // grade changed meanwhile
			grade_details = details;
			dialog.set_value("salary_structure", details.salary_structure || __("None: set it on the grade"));
			// ClickUp 14yr2e586vb: an empty Sub Band list says why (e.g. Grade1 has no Sub Bands rows)
			dialog.set_df_property(
				"sub_band",
				"description",
				details.sub_bands.length
					? ""
					: `<span class="text-danger">${__("Grade {0} has no sub bands. Add them on the grade first.", [frappe.utils.escape_html(grade)])}</span>`
			);
		});
	}

	dialog.show();
	load_grade();
	alt_watch_cost_centers(dialog);
	alt_load_employment_states(dialog);
	alt_show_income_tax_slab(dialog, frm.doc.company);
}

// Employment State of the Create / Edit Salary Structure popups (ClickUp 14yr2e58ft2): saved in
// India Payroll's Employment State of the assignment (Professional Tax). Indian states and union
// territories from the server; Kerala, or the current assignment's state when editing.
function alt_employment_state_field(current) {
	return {
		fieldname: "employment_state",
		fieldtype: "Select",
		label: __("Employment State"),
		options: [current || "Kerala"],
		default: current || "Kerala",
		reqd: 1,
		description: __("The state the employee works in (Professional Tax)."),
	};
}

// Income Tax Slab of the Create / Edit popups (ClickUp 14yr2e589ev): read-only, the slab the
// assignment gets on save for the From Date (setup/income_tax_slab.py, same rule).
function alt_income_tax_slab_field() {
	return {
		fieldname: "income_tax_slab",
		fieldtype: "Data",
		label: __("Income Tax Slab"),
		read_only: 1,
		description: __("In force on the From Date; filled on save."),
	};
}

function alt_show_income_tax_slab(dialog, company) {
	const from_date = dialog.get_value("from_date");
	if (!from_date) {
		dialog.set_value("income_tax_slab", "");
		return;
	}
	frappe
		.xcall("alantech_erp.setup.income_tax_slab.get_slab_for_popup", { from_date, company })
		.then((slab) => {
			if (dialog.get_value("from_date") !== from_date) return; // changed meanwhile
			dialog.set_value("income_tax_slab", slab || __("None in force on this date"));
		});
}

function alt_load_employment_states(dialog, current) {
	frappe
		.xcall("alantech_erp.setup.salary_structure_popup.get_employment_states")
		.then(({ states, default: fallback }) => {
			if (!states.length) {
				// India Payroll not installed: no Employment State to save
				dialog.set_df_property("employment_state", "reqd", 0);
				dialog.set_df_property("employment_state", "hidden", 1);
				return;
			}
			dialog.set_df_property("employment_state", "options", states);
			dialog.set_value("employment_state", states.includes(current) ? current : fallback);
		});
}

// Cost Centers table of the Create / Edit Salary Structure popups (ClickUp 14yr2e589er): Cost Center
// + Allocation % (whole numbers, like HRMS's Employee Cost Center), total shown under it and 100%
// required; the server checks again (salary_structure_popup.clean_cost_centers).
function alt_cost_center_fields(frm, rows, get_dialog) {
	return [
		{
			fieldtype: "Section Break",
			label: __("Cost Centers"),
			description: __("Use this table to allocate the employee's salary across multiple cost centers."),
		},
		{
			fieldname: "cost_centers",
			fieldtype: "Table",
			label: __("Cost Centers"),
			in_place_edit: true,
			data: rows.map((r) => ({ cost_center: r.cost_center, percentage: r.percentage })),
			get_data: () => get_dialog().fields_dict.cost_centers.df.data,
			fields: [
				{
					fieldname: "cost_center",
					fieldtype: "Link",
					options: "Cost Center",
					label: __("Cost Center"),
					in_list_view: 1,
					reqd: 1,
					get_query: () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }),
				},
				{
					fieldname: "percentage",
					fieldtype: "Int",
					label: __("Allocation %"),
					in_list_view: 1,
					reqd: 1,
					onchange: () => alt_show_cost_center_total(get_dialog()),
				},
			],
		},
		{ fieldname: "allocation_total", fieldtype: "HTML" },
	];
}

// rows with a cost center or a percentage
function alt_cost_center_rows(dialog) {
	return (dialog.fields_dict.cost_centers.df.data || [])
		.filter((r) => r.cost_center || r.percentage)
		.map((r) => ({ cost_center: r.cost_center || null, percentage: cint(r.percentage) }));
}

function alt_cost_centers_ok(rows) {
	const total = rows.reduce((sum, r) => sum + r.percentage, 0);
	if (rows.length && total !== 100) {
		frappe.msgprint(__("Total allocation across cost centers must be 100%. It is {0}%.", [total]));
		return false;
	}
	return true;
}

function alt_show_cost_center_total(dialog) {
	const total = alt_cost_center_rows(dialog).reduce((sum, r) => sum + r.percentage, 0);
	const ok = total === 100;
	dialog.fields_dict.allocation_total.$wrapper.html(
		`<div class="${ok ? "text-muted" : "text-danger"} small">${__("Total allocation: {0}%", [total])}${
			ok ? "" : " " + __("(must be 100%)")
		}</div>`
	);
}

function alt_watch_cost_centers(dialog) {
	alt_show_cost_center_total(dialog);
	// rows added / removed / edited in the grid: keep the total current
	dialog.fields_dict.cost_centers.grid.wrapper.on("change click", () =>
		setTimeout(() => alt_show_cost_center_total(dialog), 0)
	);
}

// View Salary Structure popup (ClickUp 14yr2e586v8, setup/salary_structure_view.py): the active
// assignment with its Earnings and Deductions (basis and monthly amount from HRMS's salary slip
// preview). Edit, for the HR Manager only (checked on the server too), makes a new assignment
// from a later From Date with the chosen Sub Band; the current one stays for the months before.
function alt_view_salary_structure(frm) {
	const method = "alantech_erp.setup.salary_structure_view.";
	frappe.xcall(method + "get_salary_structure_view", { employee: frm.doc.name }).then((view) => {
		const esc = frappe.utils.escape_html;
		const money = (value) =>
			value === null || value === undefined ? "-" : format_currency(value, view.currency);
		const table = (title, rows, total) => `
			<h5 class="mt-4 mb-2">${esc(title)}</h5>
			<table class="table table-bordered table-sm">
				<thead><tr><th>${__("Component")}</th><th>${__("Formula / Percentage")}</th>
					<th class="text-right">${__("Amount")}</th></tr></thead>
				<tbody>${
					rows.length
						? rows
								.map(
									(r) => `<tr><td>${esc(r.component)}</td><td>${esc(r.basis)}</td>
									<td class="text-right">${money(r.amount)}</td></tr>`
								)
								.join("")
						: `<tr><td colspan="3" class="text-muted">${__("None")}</td></tr>`
				}</tbody>
				<tfoot><tr><th colspan="2">${__("Total")}</th><th class="text-right">${money(total)}</th></tr></tfoot>
			</table>`;
		const link = `<a href="/app/salary-structure-assignment/${encodeURIComponent(view.assignment)}">${esc(view.assignment)}</a>`;
		const summary = [
			[__("Salary Structure"), esc(view.salary_structure)],
			[__("Assignment"), link],
			[__("From Date"), esc(frappe.datetime.str_to_user(view.from_date))],
			[__("Grade"), esc(view.grade || "-")],
			[__("Sub Band"), esc(view.sub_band || "-")],
			[__("Base (Gross)"), money(view.base)],
			[__("Income Tax Slab"), esc(view.income_tax_slab || "-")],
			[__("Employment State"), esc(view.employment_state || "-")],
			[
				__("Cost Centers"),
				(view.cost_centers || []).map((r) => `${esc(r.cost_center)} (${cint(r.percentage)}%)`).join("<br>") || "-",
			],
		]
			.map(([label, value]) => `<div class="col-sm-4 mb-2"><div class="text-muted small">${label}</div><div>${value}</div></div>`)
			.join("");

		const dialog = new frappe.ui.Dialog({
			title: __("Salary Structure"),
			size: "large",
			fields: [{ fieldname: "body", fieldtype: "HTML" }],
		});
		dialog.fields_dict.body.$wrapper.html(`
			<div class="row">${summary}</div>
			${view.amount_error ? `<div class="alert alert-warning">${__("Amounts could not be worked out")}: ${esc(view.amount_error)}</div>` : ""}
			${table(__("Earnings"), view.earnings, view.total_earnings)}
			${table(__("Deductions"), view.deductions, view.total_deductions)}
			<div class="text-right font-weight-bold">${__("Net Pay")}: ${money(view.net)}</div>
			<div class="text-muted small mt-2">${__("Monthly amounts for a full month, before deductions for unpaid days.")}</div>`);
		if (view.can_edit) {
			dialog.set_primary_action(__("Edit"), () => {
				dialog.hide();
				alt_edit_salary_structure(frm, view);
			});
		}
		dialog.show();
	});
}

function alt_edit_salary_structure(frm, view) {
	const method = "alantech_erp.setup.salary_structure_";
	let sub_bands = [];
	let ready = false;
	const today = frappe.datetime.get_today();
	const dialog = new frappe.ui.Dialog({
		title: __("Edit Salary Structure"),
		fields: [
			// how to edit (ClickUp 14yr2e586vb sign-off point): a new assignment keeps the salary
			// history; correcting cancels and amends the current one, refused on the server once a
			// submitted salary slip uses it
			{
				fieldname: "edit_mode",
				fieldtype: "Select",
				label: __("How"),
				options: [
					{ value: "new", label: __("New assignment from a new From Date") },
					{ value: "amend", label: __("Correct the current assignment (cancel and amend)") },
				],
				default: "new",
				reqd: 1,
				onchange: () => ready && set_mode(), // not while the dialog is being built
			},
			{ fieldname: "mode_note", fieldtype: "HTML" },
			{ fieldname: "grade", fieldtype: "Link", options: "Employee Grade", label: __("Grade"), default: frm.doc.grade, read_only: 1 },
			{
				fieldname: "sub_band",
				fieldtype: "Link",
				options: "Sub Band",
				label: __("Sub Band"),
				reqd: 1,
				default: view.sub_band,
				get_query: () => ({ filters: { name: ["in", sub_bands.map((r) => r.sub_band)] } }),
				onchange: () => {
					const row = sub_bands.find((r) => r.sub_band === dialog.get_value("sub_band"));
					dialog.set_value("gross_amount", row ? row.gross_amount : null);
				},
			},
			{ fieldname: "gross_amount", fieldtype: "Currency", label: __("Gross Amount"), read_only: 1 },
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
				reqd: 1,
				default: today > view.from_date ? today : null,
				description: __("After {0}.", [frappe.datetime.str_to_user(view.from_date)]),
				depends_on: "eval:doc.edit_mode==='new'",
				mandatory_depends_on: "eval:doc.edit_mode==='new'",
				onchange: () => alt_show_income_tax_slab(dialog, frm.doc.company),
			},
			// the current assignment's state; changed when the employee moves to another state
			alt_employment_state_field(view.employment_state),
			alt_income_tax_slab_field(),
			{ fieldname: "submit", fieldtype: "Check", label: __("Submit"), default: 1, description: __("Untick to keep the new assignment as a draft.") },
			// the current assignment's split, else the employee's Payroll Cost Center
			...alt_cost_center_fields(
				frm,
				view.cost_centers && view.cost_centers.length
					? view.cost_centers
					: frm.doc.payroll_cost_center
					? [{ cost_center: frm.doc.payroll_cost_center, percentage: 100 }]
					: [],
				() => dialog
			),
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			const cost_centers = alt_cost_center_rows(dialog);
			if (!alt_cost_centers_ok(cost_centers)) return;
			dialog.disable_primary_action();
			frappe
				.xcall(method + "view.revise_salary_structure", {
					cost_centers,
					employee: frm.doc.name,
					sub_band: values.sub_band,
					from_date: values.edit_mode === "amend" ? null : values.from_date,
					employment_state: values.employment_state,
					submit: values.submit ? 1 : 0,
					mode: values.edit_mode,
				})
				.then((r) => {
					dialog.hide();
					const link = `<a href="/app/salary-structure-assignment/${encodeURIComponent(r.name)}">${frappe.utils.escape_html(r.name)}</a>`;
					const status = r.docstatus === 1 ? __("submitted") : __("saved as draft");
					frappe.show_alert({
						message: r.amended_from
							? __("Salary Structure Assignment {0} {1}; {2} cancelled", [link, status, frappe.utils.escape_html(r.amended_from)])
							: __("Salary Structure Assignment {0} {1}", [link, status]),
						indicator: "green",
					});
					frm.reload_doc();
				})
				.finally(() => dialog.enable_primary_action());
		},
	});
	// the note and the From Date follow the chosen way; correcting keeps the current From Date
	function set_mode() {
		const amend = dialog.get_value("edit_mode") === "amend";
		const current = frappe.utils.escape_html(view.assignment);
		const since = frappe.datetime.str_to_user(view.from_date);
		dialog.fields_dict.mode_note.$wrapper.html(
			`<p class="text-muted">${
				amend
					? __(
							"The current assignment ({0}, from {1}) is cancelled and replaced by a corrected copy from the same date. Only possible while no submitted salary slip uses it.",
							[current, since]
					  )
					: __("A new assignment starts on the From Date below. The current one ({0}, from {1}) stays for the months before.", [
							current,
							since,
					  ])
			}</p>`
		);
		dialog.set_value("from_date", amend ? view.from_date : today > view.from_date ? today : null);
		alt_show_income_tax_slab(dialog, frm.doc.company);
	}

	dialog.show();
	ready = true;
	set_mode();
	alt_watch_cost_centers(dialog);
	alt_load_employment_states(dialog, view.employment_state);
	if (frm.doc.grade) {
		frappe.xcall(method + "popup.get_grade_details", { grade: frm.doc.grade }).then((details) => {
			sub_bands = details.sub_bands;
			const row = sub_bands.find((r) => r.sub_band === dialog.get_value("sub_band"));
			dialog.set_value("gross_amount", row ? row.gross_amount : null);
		});
	}
}

// Bank / statutory numbers (UAN, ESIC IP, IFSC, MICR, PF, Bank A/C, IBAN, names): checked as soon
// as a value is entered, shown in red under the field; the save is refused by
// employee_bank_details.validate_bank_details with the same messages.
const ALT_BANK_FIELDS = [
	"uan_number", "pf_name", "esic_card_no", "ifsc_code", "alt_ifsc_code", "micr_code",
	"provident_fund_account", "bank_ac_no", "alt_bank_account_holder", "bank_name",
	"alt_bank_branch", "iban",
];

function alt_check_bank_field(frm, fieldname) {
	const field = frm.fields_dict[fieldname];
	if (!field) return;
	if (field.alt_description === undefined) field.alt_description = field.df.description || "";
	const value = frm.doc[fieldname] || "";
	const show = (error) => {
		field.df.invalid = !!error;
		field.set_invalid();
		field.set_description(
			error ? `<span class="text-danger">${__(field.df.label)} ${error}</span>` : field.alt_description
		);
	};
	if (!value) return show(null);
	frappe
		.xcall("alantech_erp.setup.employee_bank_details.check_bank_field", { fieldname, value })
		.then((r) => {
			if ((frm.doc[fieldname] || "") !== value) return; // changed again meanwhile
			if (r.value && r.value !== value) frm.set_value(fieldname, r.value); // upper-cased / spaces removed
			show(r.error);
		});
}

frappe.ui.form.on(
	"Employee",
	Object.fromEntries(ALT_BANK_FIELDS.map((f) => [f, (frm) => alt_check_bank_field(frm, f)]))
);

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
		alt_doc.check_number(frm, "open");
		alt_doc.format_number_on_blur(frm);
		alt_doc.check_number_on_input(frm);
		alt_doc.limit_date_pickers(frm);
		alt_doc.add_review_buttons(frm);
	},

	document_type(frm) {
		alt_doc.set_card_number_label(frm);
		alt_doc.check_number(frm, "typing");
	},

	card_number(frm) {
		// fires while typing: message under the field only, no popup
		alt_doc.check_number(frm, "typing");
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
		const error = alt_doc.local_number_error(frm, frm.doc.card_number);
		if (error) {
			frappe.throw({
				title: __("Invalid {0} Number", [__(frm.doc.document_type)]),
				message: error,
				indicator: "red",
			});
		}
	},
	issue_date(frm) {
		const d = frm.doc.issue_date;
		if (d && frappe.datetime.get_day_diff(d, frappe.datetime.get_today()) > 0) {
			frappe.msgprint({
				title: __("Invalid Issue Date"),
				message: __("Issue Date cannot be in the future."),
				indicator: "orange",
			});
			frm.set_value("issue_date", null);
		}
		alt_doc.check_expiry_after_issue(frm);
	},

	expiry_date(frm) {
		const d = frm.doc.expiry_date;
		if (d && frappe.datetime.get_day_diff(d, frappe.datetime.get_today()) < 0) {
			frappe.msgprint({
				title: __("Invalid Expiry Date"),
				message: __("Expiry Date cannot be in the past."),
				indicator: "orange",
			});
			frm.set_value("expiry_date", null);
			return;
		}
		alt_doc.check_expiry_after_issue(frm);
	},
});
const ALT_DOC_STATUS = { PENDING: "Pending Approval", APPROVED: "Approved", REJECTED: "Rejected" };

// Server-set fields, ignored by the "has anything changed?" check
const ALT_DOC_SYSTEM_FIELDS = new Set([
	"reference_title", "employee", "expiry_required", "expiry_date_mandatory",
	"issue_date_required", "issue_date_mandatory",
	"approval_status", "submitted_by", "reviewed_by", "reviewed_on", "rejection_reason",
]);

// Check digits of the built-in Number Formats (document_number.FORMATS)
const ALT_DOC_CHECK_DIGITS = {
	// Aadhaar. Tables built from the D5 group and its permutation instead of typed out
	// (a typed table got one row wrong once, see document_number.py)
	verhoeff(digits) {
		const d = (j, k) =>
			j < 5 ? (k < 5 ? (j + k) % 5 : 5 + ((j + k) % 5)) : k < 5 ? 5 + ((j - k + 5) % 5) : (j - k + 5) % 5;
		const p1 = [1, 5, 7, 6, 2, 8, 3, 0, 9, 4];
		const p = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]];
		for (let i = 1; i < 8; i++) p.push(p[i - 1].map((x) => p1[x]));
		let c = 0;
		[...digits].reverse().forEach((ch, i) => (c = d(c, p[i % 8][+ch])));
		return c === 0;
	},
	// Emirates ID
	luhn(digits) {
		let sum = 0;
		[...digits].reverse().forEach((ch, i) => {
			let n = +ch;
			if (i % 2) n = n * 2 > 9 ? n * 2 - 9 : n * 2;
			sum += n;
		});
		return sum % 10 === 0;
	},
};

const alt_doc = {
	// Visa -> Visa Number, Passport -> Passport Number, other -> "<Type> Number"
	set_card_number_label(frm) {
		const t = frm.doc.document_type;
		frm.set_df_property("card_number", "label", t ? __("{0} Number", [__(t)]) : __("Card Number"));
	},

	// Number Format of the Document Type (document_number.py). The result shows under the field:
	// the format example, or in red why the number is wrong (bad format, already used).
	//   "open":   also an orange warning at the top for an existing document with a wrong number
	//             (the server blocks saving it until the number is fixed)
	//   "typing": message only, the number is left as typed
	//   "blur":   on leaving the field, a valid number is written the standard way
	//             (e.g. Aadhaar "2345 6789 0124")
	check_number(frm, mode) {
		const { document_type, card_number } = frm.doc;
		if (!document_type) return;
		const request = (frm.__alt_number_request = (frm.__alt_number_request || 0) + 1);
		const local_error = mode === "open" ? null : alt_doc.local_number_error(frm, card_number);
		if (local_error) {
			// wrong format or check digit: already shown by check_number_on_input, no server call
			alt_doc.set_number_message(frm, local_error);
			return;
		}
		frappe
			.xcall("alantech_erp.alantech.doctype.document.document_number.check_number", {
				document_type,
				number: card_number || "",
				name: frm.is_new() ? null : frm.doc.name,
			})
			.then((r) => {
				// a newer check started while this one ran (still typing)
				if (request !== frm.__alt_number_request || frm.doc.document_type !== document_type) return;
				frm.__alt_number_rules = { ...r.rules, document_type, example: r.example };
				alt_doc.set_number_message(frm, r.error);
				frm.toggle_reqd("card_number", !!r.mandatory);
				if (mode === "open") {
					if (r.error) {
						frm.dashboard.set_headline_alert(
							`${r.error} ${__("Correct the number to save this document.")}`,
							"orange"
						);
					}
					return;
				}
				if (!r.error) frm.dashboard.clear_headline();
				if (mode === "blur" && !r.error && r.value !== (card_number || "")) {
					frm.set_value("card_number", r.value);
				}
			});
	},

	format_number_on_blur(frm) {
		const $input = frm.fields_dict.card_number?.$input;
		if (!$input) return;
		$input.off("blur.alt_number").on("blur.alt_number", () => {
			// let the field pass the typed value to frm.doc first
			setTimeout(() => alt_doc.check_number(frm, "blur"), 300);
		});
	},

	// On every key press: format and check digit are checked here straight away (field turns red);
	// the server is asked only once the number is valid, for duplicates (card_number -> check_number)
	check_number_on_input(frm) {
		const $input = frm.fields_dict.card_number?.$input;
		if (!$input) return;
		$input.off("input.alt_number").on("input.alt_number", () => {
			if (!alt_doc.has_live_rules(frm)) return;
			frm.__alt_number_request = (frm.__alt_number_request || 0) + 1; // drop older server answers
			alt_doc.set_number_message(frm, alt_doc.local_number_error(frm, $input.val()));
		});
	},

	has_live_rules(frm) {
		const rules = frm.__alt_number_rules;
		return !!(rules && rules.pattern && rules.document_type === frm.doc.document_type);
	},

	// Same checks as document_number.clean_number; null when valid, empty or not checkable here
	local_number_error(frm, value) {
		if (!alt_doc.has_live_rules(frm)) return null;
		const rules = frm.__alt_number_rules;
		const number = (value || "").trim().replace(/\s+/g, " ");
		if (!number) return null; // mandatory is checked by the field itself
		const compact = rules.compact ? number.replace(/[\s\-./]/g, "").toUpperCase() : number;
		let regex;
		try {
			regex = new RegExp(`^(?:${rules.pattern})$`);
		} catch (e) {
			return null; // Custom Pattern only Python understands: left to the server
		}
		const bold = (v) => `<strong>${frappe.utils.escape_html(v)}</strong>`;
		const type = frm.doc.document_type;
		if (regex.test(compact)) {
			const check = ALT_DOC_CHECK_DIGITS[rules.check_digit];
			if (!check || check(compact)) return null;
			return __(
				"{0} is not a valid {1} number: the check digit does not match. " +
					"A digit is probably mistyped; compare it with the card.",
				[bold(number), type]
			);
		}
		if (rules.example) {
			return __("{0} is not a valid {1} number. It should look like {2}.", [bold(number), type, bold(rules.example)]);
		}
		return __("{0} is not a valid {1} number.", [bold(number), type]);
	},

	// Message under the Number field: the error in red (field marked invalid), else the format example
	set_number_message(frm, error) {
		const field = frm.fields_dict.card_number;
		if (!field) return;
		const example = frm.__alt_number_rules?.example;
		field.df.invalid = !!error;
		field.set_invalid();
		field.set_description(
			error ? `<span class="text-danger">${error}</span>` : example ? __("Format: {0}", [example]) : ""
		);
	},

	// Issue Date up to today, Expiry Date from today: other days cannot be picked in the calendar
	// (typed dates are checked by issue_date / expiry_date above, and by the server)
	limit_date_pickers(frm) {
		const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
		const limits = { issue_date: { max_date: today }, expiry_date: { min_date: today } };
		for (const [fieldname, limit] of Object.entries(limits)) {
			const field = frm.fields_dict[fieldname];
			if (!field) continue;
			Object.assign(field.df, limit); // pickers built later (field shown by depends_on)
			field.datepicker?.update({ minDate: limit.min_date, maxDate: limit.max_date });
		}
	},

	check_expiry_after_issue(frm) {
		const { issue_date, expiry_date } = frm.doc;
		if (issue_date && expiry_date && frappe.datetime.get_day_diff(expiry_date, issue_date) <= 0) {
			frappe.msgprint({
				title: __("Invalid Expiry Date"),
				message: __("Expiry Date must be after the Issue Date."),
				indicator: "orange",
			});
			frm.set_value("expiry_date", null);
		}
	},

	snapshot_of(frm) {
		const values = {};
		(frm.meta.fields || []).forEach((df) => {
			if (frappe.model.no_value_type.includes(df.fieldtype)) return;
			if (ALT_DOC_SYSTEM_FIELDS.has(df.fieldname)) return;
			const v = frm.doc[df.fieldname];
			values[df.fieldname] = v === undefined || v === null ? "" : String(v);
		});
		// tables are skipped above (no_value_type): adding or removing a file is a change too
		values.attachments = (frm.doc.attachments || []).map((row) => [row.file || "", row.description || ""]);
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

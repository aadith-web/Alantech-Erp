// Employee import: one summary of the users created (and welcome emails sent) once every row is
// in, instead of a message per row. Notes are collected by setup/employee_user.py.
// Loaded through doctype_js in hooks.py; the import dialog of the Employee list uses this form too.

// Employee import template (https://app.clickup.com/t/14yr2e57mja): Series stays ticked (it is
// mandatory) and its description says the blank template comes with it pre-filled (HR-EMP-,
// setup/employee_import.py). Employee Number is ticked through in_import_template
// (setup/employee_fields.py). Frappe defines the exporter class when data_import_tools.bundle.js
// loads, so it is patched as soon as it is set.
// Fields needed to create an employee (ClickUp 14yr2e57mhp) are ticked by "Select Mandatory"
// (in_import_template, setup/employee_payroll_fields.py) and marked here. Same list as
// employee_validation.REQUIRED_ON_CREATE.
const ALT_REQUIRED_TO_CREATE = [
	"first_name", "gender", "date_of_birth", "date_of_joining", "company", "status",
	"department", "designation", "branch", "reports_to", "employment_type", "cell_number",
	"default_shift", "grade",
	// Nationality (ClickUp 14yr2e57r7h, setup/employee_nationality.py)
	"alt_nationality",
];
const ALT_ONE_EMAIL = ["company_email", "personal_email"];
// mandatory when Nationality is India (ClickUp 14yr2e57r7k, setup/employee_nationality.py)
const ALT_INDIA_REQUIRED = ["alt_aadhaar_number", "pan_number"];

(() => {
	const patch = (DataExporter) => {
		if (!DataExporter || DataExporter.alt_employee_series) return DataExporter;
		const get_options = DataExporter.prototype.get_multicheck_options;
		DataExporter.prototype.get_multicheck_options = function (group) {
			const options = get_options.call(this, group);
			if (
				this.doctype !== "Employee" ||
				group.fieldname !== "Employee" ||
				this.exporting_for !== "Insert New Records"
			) {
				return options;
			}
			const series = (frappe.meta.get_docfield("Employee", "naming_series")?.options || "")
				.split("\n")
				.find((s) => s.trim());
			for (const option of options) {
				if (option.value === "naming_series" && series) {
					option.description = __("naming_series (Mandatory, pre-filled: {0})", [series]);
				} else if (ALT_REQUIRED_TO_CREATE.includes(option.value)) {
					// not reqd in the DocType, but the employee is refused without it
					option.danger = true;
					option.description = __("{0} (Mandatory)", [option.value]);
				} else if (ALT_INDIA_REQUIRED.includes(option.value)) {
					option.description = __("{0} (Mandatory when Nationality is India)", [option.value]);
				} else if (ALT_ONE_EMAIL.includes(option.value)) {
					option.description = __("{0} (Company or Personal Email mandatory)", [option.value]);
				}
			}
			return options;
		};
		DataExporter.alt_employee_series = true;
		return DataExporter;
	};

	frappe.provide("frappe.data_import");
	let current = patch(frappe.data_import.DataExporter);
	Object.defineProperty(frappe.data_import, "DataExporter", {
		configurable: true,
		enumerable: true,
		get: () => current,
		set: (cls) => {
			current = patch(cls);
		},
	});
})();

frappe.ui.form.on("Data Import", {
	setup(frm) {
		const handler = ({ data_import }) => {
			if (data_import !== frm.doc.name || frm.doc.reference_doctype !== "Employee") return;
			frappe
				.xcall("alantech_erp.setup.employee_user.pop_import_notes", { data_import })
				.then(alt_import_summary);
		};
		frappe.realtime.on("data_import_refresh", handler);
		// switched off with the form's own handlers when the import dialog closes
		frm._realtime_handlers?.push(["data_import_refresh", handler]);
	},
});

function alt_import_summary(notes) {
	if (!notes || !notes.length) return;
	const created = notes.filter((n) => n.user);
	const welcomed = created.filter((n) => n.welcome_email);
	const skipped = notes.filter((n) => !n.user);
	const list = (rows, line) => `<ul>${rows.map((n) => `<li>${line(n)}</li>`).join("")}</ul>`;

	let html = "";
	if (created.length) {
		html += `<p>${__("Users created: {0}", [created.length])}</p>`;
		html += list(created, (n) => `${frappe.utils.escape_html(n.employee)} &lt;${frappe.utils.escape_html(n.user)}&gt;`);
	}
	if (welcomed.length) {
		html += `<p>${__("Welcome email sent to {0} user(s).", [welcomed.length])}</p>`;
	}
	if (skipped.length) {
		html += `<p>${__("No user created: {0}", [skipped.length])}</p>`;
		html += list(skipped, (n) => `${frappe.utils.escape_html(n.employee)}: ${frappe.utils.escape_html(n.reason)}`);
	}
	frappe.msgprint({
		title: __("Employee Users"),
		message: html,
		indicator: skipped.length ? "orange" : "green",
	});
}

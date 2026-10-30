// Employee import: one summary of the users created (and welcome emails sent) once every row is
// in, instead of a message per row. Notes are collected by setup/employee_user.py.
// Loaded through doctype_js in hooks.py; the import dialog of the Employee list uses this form too.

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

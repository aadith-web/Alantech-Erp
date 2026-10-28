// Shift Request: picking an Employee showed "Please select Employee first."
// Approver is fetched from employee.shift_request_approver while the Employee value is still being
// validated (frm.doc.employee not set yet), and Frappe v16 validates the fetched Approver through
// HRMS's get_approvers query, which throws without an employee. Until there is an employee, the
// Approver is checked as a plain User; after that, HRMS's approver query applies as before.
// Loaded through doctype_js in hooks.py, after HRMS's own Shift Request script.

frappe.ui.form.on("Shift Request", {
	setup(frm) {
		frm.set_query("approver", () => {
			if (!frm.doc.employee) return {};
			return {
				query: "hrms.hr.doctype.department_approver.department_approver.get_approvers",
				filters: {
					employee: frm.doc.employee,
					doctype: frm.doc.doctype,
				},
			};
		});
	},
});

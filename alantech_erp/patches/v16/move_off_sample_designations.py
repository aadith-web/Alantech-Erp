"""Move the records still on two ERPNext sample designations to org chart posts (AIS-MS-TP-01), then
delete the sample designations (see remove_sample_designations, which kept them as linked).

Decided with HR (2026-11-23):
- Employees on Accountant become Accounts Executive. Written directly, so nothing else changes on
  them: Reports To and their users' roles stay as they are (no role profile is applied). The
  designation shown on their Salary Structure Assignments and Uniform Issues follows.
- Loan Rules: an Accountant row becomes Accounts Head, an Administrative Officer row is removed
  (a rule that already lists Accounts Head keeps one row).
"""

import frappe

EMPLOYEE_MOVES = {"Accountant": "Accounts Executive"}
LOAN_RULE_MOVES = {"Accountant": "Accounts Head", "Administrative Officer": None}
SNAPSHOT_DOCTYPES = ("Salary Structure Assignment", "Employee Uniform Issue")


def execute():
	for old, new in EMPLOYEE_MOVES.items():
		if not frappe.db.exists("Designation", new):
			continue
		frappe.db.set_value("Employee", {"designation": old}, "designation", new, update_modified=False)
		for doctype in SNAPSHOT_DOCTYPES:
			if frappe.db.exists("DocType", doctype) and frappe.get_meta(doctype).has_field("designation"):
				frappe.db.set_value(doctype, {"designation": old}, "designation", new, update_modified=False)

	if frappe.db.exists("DocType", "Loan Rule Designation"):
		for old, new in LOAN_RULE_MOVES.items():
			for row in frappe.get_all("Loan Rule Designation", filters={"designation": old}, fields=["name", "parent"]):
				listed = new and frappe.db.exists("Loan Rule Designation", {"parent": row.parent, "designation": new})
				if new and not listed:
					frappe.db.set_value("Loan Rule Designation", row.name, "designation", new, update_modified=False)
				else:
					frappe.db.delete("Loan Rule Designation", {"name": row.name})

	for name in set(EMPLOYEE_MOVES) | set(LOAN_RULE_MOVES):
		if frappe.db.exists("Designation", name):
			try:
				frappe.delete_doc("Designation", name, ignore_permissions=True)
			except frappe.LinkExistsError:
				frappe.clear_messages()
				print(f"Designation {name} is still linked; kept")

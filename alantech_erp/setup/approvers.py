"""Default approvers on the Employee.

* Leave Approver: the Reports To employee's user. It is the first step of the Leave Approval
  workflow (setup/leave_workflow.py); HR Manager approves after it. With no Reports To (or a
  manager without a user) it is the HR Manager, who then approves in one step. The Managing
  Director has none: nobody approves his leave.
* Expense Approver and Shift Request Approver: the HR Manager's user (the first created active
  employee with the HR Manager designation). The HR Manager's own requests go to their Reports To.

Only empty fields are filled. The fields themselves are filled (not a lookup at approval time)
because HRMS reads them in many places: the Leave Application default, the approver dropdowns,
Shift Request validation, Expense Claim, and the approver roles it gives on Employee.on_update.

A value that came from a default follows it: when Reports To changes, the manager's user
changes, or another person becomes HR Manager, it is replaced. A value HR picked by hand is never
touched.

hooks.py:
    doc_events = {"Employee": {"validate": [..., "alantech_erp.setup.approvers.employee_validate"],
                               "on_update": [..., "alantech_erp.setup.approvers.employee_on_update"]}}
    after_migrate = [..., "alantech_erp.setup.approvers.execute"]
"""

import frappe

HR_DESIGNATION = "HR Manager"
TOP_DESIGNATION = "Managing Director"
UNCHANGED = object()  # refresh(): "this default did not change"
REPORTS_TO_FIELDS = ("leave_approver",)
HR_FIELDS = ("expense_approver", "shift_request_approver")
APPROVER_FIELDS = REPORTS_TO_FIELDS + HR_FIELDS


def manager_user(employee):
	return frappe.db.get_value("Employee", employee, "user_id") if employee else None


def hr_manager_user():
	holders = frappe.get_all(
		"Employee",
		filters={"designation": HR_DESIGNATION, "status": "Active", "user_id": ["is", "set"]},
		pluck="user_id",
		order_by="creation asc",
		limit=1,
	)
	return holders[0] if holders else None


def defaults_for(user_id, reports_to_user, hr_user, designation=None):
	"""field -> default user, never the employee themselves."""
	if designation == TOP_DESIGNATION:
		return {f: None for f in APPROVER_FIELDS}  # the Managing Director answers to nobody
	leave_user = reports_to_user or hr_user
	if hr_user == user_id:
		hr_user = reports_to_user  # the HR Manager's own expenses and shifts
	out = {f: leave_user for f in REPORTS_TO_FIELDS}
	out.update({f: hr_user for f in HR_FIELDS})
	return {f: (None if u == user_id else u) for f, u in out.items()}


def apply_defaults(doc, old_defaults, new_defaults):
	"""Fill empty fields, and replace values that were the old default. Returns True if changed."""
	changed = False
	for field in APPROVER_FIELDS:
		value, old, new = doc.get(field), old_defaults.get(field), new_defaults.get(field)
		if (not value or (old and value == old)) and value != new:
			doc.set(field, new)
			changed = True
	return changed


# ---------------------------------------------------------------------- Employee doc_events
def employee_validate(doc, method=None):
	"""Runs after org_structure.apply_designation_defaults, which may fill Reports To."""
	hr_user = hr_manager_user()
	before = doc.get_doc_before_save()
	old = (
		defaults_for(doc.user_id, manager_user(before.reports_to), hr_user, before.designation)
		if before
		else {}
	)
	apply_defaults(doc, old, defaults_for(doc.user_id, manager_user(doc.reports_to), hr_user, doc.designation))


def employee_on_update(doc, method=None):
	before = doc.get_doc_before_save()
	user_changed(doc, before.user_id if before else None, before)


def user_changed(doc, old_user, before=None):
	"""Also called by employee_user.create_user, which writes user_id with db_set before saving,
	so the save alone cannot see the change."""
	# a manager got (or changed) their user: pass it on to the employees reporting to them
	if old_user != doc.user_id:
		for name in frappe.get_all("Employee", filters={"reports_to": doc.name}, pluck="name"):
			refresh(name, old_reports_to_user=old_user)

	# the HR Manager changed: move the approvers that followed the old one
	was_hr = bool(before) and before.designation == HR_DESIGNATION and before.status == "Active"
	is_hr = doc.designation == HR_DESIGNATION and doc.status == "Active"
	if (was_hr or is_hr) and (not before or was_hr != is_hr or old_user != doc.user_id):
		old_hr = old_user if was_hr else None
		for name in frappe.get_all("Employee", filters={"status": "Active"}, pluck="name"):
			refresh(name, old_hr_user=old_hr)


def refresh(employee, old_reports_to_user=UNCHANGED, old_hr_user=UNCHANGED):
	"""Save only when something changes, so HRMS's on_update gives the approver roles."""
	emp = frappe.get_doc("Employee", employee)
	reports_to_user, hr_user = manager_user(emp.reports_to), hr_manager_user()
	old = defaults_for(
		emp.user_id,
		reports_to_user if old_reports_to_user is UNCHANGED else old_reports_to_user,
		hr_user if old_hr_user is UNCHANGED else old_hr_user,
		emp.designation,
	)
	new = defaults_for(emp.user_id, reports_to_user, hr_user, emp.designation)
	if apply_defaults(emp, old, new):
		emp.flags.ignore_permissions = True
		emp.save()


# ---------------------------------------------------------------------- after_migrate
def execute():
	"""Fill empty approvers on existing employees. Values set by hand are left alone."""
	for row in frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", *APPROVER_FIELDS]):
		if not all(row.get(f) for f in APPROVER_FIELDS):
			refresh(row.name)
	frappe.db.commit()

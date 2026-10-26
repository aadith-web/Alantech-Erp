"""Block leave for a gender the Leave Type is not applicable to."""

import frappe
from frappe import _
from frappe.utils import cint

GENDER_FIELD = {"Male": "alt_for_male", "Female": "alt_for_female"}


def is_applicable(leave_type, gender):
	field = GENDER_FIELD.get(gender)
	if not field or not leave_type:
		return True  # other genders / no type: no restriction
	value = frappe.db.get_value("Leave Type", leave_type, field)
	return value is None or bool(cint(value))


def check_gender(doc):
	gender = frappe.db.get_value("Employee", doc.employee, "gender")
	if not is_applicable(doc.leave_type, gender):
		frappe.throw(
			_("{0} is not applicable to {1} employees ({2}).").format(
				frappe.bold(doc.leave_type), _(gender), doc.employee_name or doc.employee
			),
			title=_("Leave Type Not Applicable"),
		)


def validate_leave_application(doc, method=None):
	check_gender(doc)


def validate_leave_allocation(doc, method=None):
	# allocations made by a Leave Policy Assignment are not blocked here (it would stop the whole
	# policy for that employee); the Leave Application check above still stops them using it
	if doc.get("leave_policy_assignment"):
		return
	check_gender(doc)

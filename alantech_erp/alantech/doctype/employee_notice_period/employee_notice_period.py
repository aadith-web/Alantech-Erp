# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Notice Period: one record per employee, created with the employee.

ClickUp: https://app.clickup.com/t/14yr2e57r71 (parent HR-F07 14yr2e56cak)

- Saving a new Employee creates its Employee Notice Period (named after the Employee ID) with the
  company policy notice: HR Settings > Default Notice Period (Days), 30 when not set. Nothing for
  HR to create by hand. A Notice (days) typed on the new employee is used instead.
- The record is shown on the Employee's Notice Period tab (public/js/employee.js).
- ERPNext's own Employee field Notice (days) (Exit tab, notice_number_of_days) always shows the
  same number: a change on either side is copied to the other.
- Source: Company Policy while the days equal the default, Manual when HR set another number.
- Employees (no HR role) see only their own record; HR User / HR Manager / System Manager see all.

Hooks (hooks.py): Employee on_update -> employee_on_update, on_trash -> employee_on_trash;
permission_query_conditions / has_permission; after_migrate -> execute (HR Settings field and the
Employee tab). Existing employees: patches/v16/employee_notice_periods.py.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.document import Document
from frappe.utils import cint

DOCTYPE = "Employee Notice Period"
DEFAULT_NOTICE_DAYS = 30
SETTINGS_FIELD = "alt_default_notice_days"
HR_ROLES = {"System Manager", "HR Manager", "HR User"}
COMPANY_POLICY, MANUAL = "Company Policy", "Manual"

CUSTOM_FIELDS = {
	"HR Settings": [
		{
			"fieldname": SETTINGS_FIELD,
			"fieldtype": "Int",
			"label": "Default Notice Period (Days)",
			"default": str(DEFAULT_NOTICE_DAYS),
			"non_negative": 1,
			"insert_after": "retirement_age",
			"description": "Company policy notice period given to every new employee "
			"(Employee Notice Period). Change it per employee on the employee's Notice Period tab.",
		}
	],
	"Employee": [
		{
			"fieldname": "alt_notice_period_tab",
			"fieldtype": "Tab Break",
			"label": "Notice Period",
			"insert_after": "old_parent",  # last field before the Connections tab
		},
		{
			"fieldname": "alt_notice_period_html",
			"fieldtype": "HTML",
			"label": "Notice Period",
			"insert_after": "alt_notice_period_tab",
		},
	],
}


class EmployeeNoticePeriod(Document):
	def validate(self):
		if cint(self.notice_days) < 0:
			frappe.throw(_("Notice Days cannot be negative."), title=_("Invalid Notice Days"))
		self.source = COMPANY_POLICY if cint(self.notice_days) == get_default_notice_days() else MANUAL

	def on_update(self):
		# ERPNext's Notice (days) on the Employee shows the same number (no Employee save: no hooks)
		if cint(frappe.db.get_value("Employee", self.employee, "notice_number_of_days")) != cint(self.notice_days):
			frappe.db.set_value(
				"Employee", self.employee, "notice_number_of_days", cint(self.notice_days), update_modified=False
			)


# ---------------------------------------------------------------------- default
def default_saved():
	return bool(
		frappe.db.sql(
			"select 1 from `tabSingles` where doctype = 'HR Settings' and field = %s", SETTINGS_FIELD
		)
	)


def get_default_notice_days():
	"""HR Settings > Default Notice Period (Days); 30 until HR Settings has a value."""
	if not default_saved():
		return DEFAULT_NOTICE_DAYS
	return cint(frappe.db.get_single_value("HR Settings", SETTINGS_FIELD, cache=False))


# ---------------------------------------------------------------------- Employee hooks
def employee_on_update(doc, method=None):
	"""New employee: create the notice period. Notice (days) changed on the Employee: copy it."""
	name = frappe.db.get_value(DOCTYPE, {"employee": doc.name})
	days = cint(doc.notice_number_of_days)
	if not name:
		create_notice_period(doc)
	elif doc.has_value_changed("notice_number_of_days"):
		record = frappe.get_doc(DOCTYPE, name)
		if not days:  # cleared on the Employee: the notice period still applies, show it again
			frappe.db.set_value(
				"Employee", doc.name, "notice_number_of_days", cint(record.notice_days), update_modified=False
			)
			doc.notice_number_of_days = cint(record.notice_days)
		elif cint(record.notice_days) != days:
			record.notice_days = days
			record.save(ignore_permissions=True)


def create_notice_period(employee):
	days = cint(employee.notice_number_of_days) or get_default_notice_days()
	record = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"employee": employee.name,
			"notice_days": days,
			"effective_from": employee.date_of_joining,
		}
	).insert(ignore_permissions=True)
	employee.notice_number_of_days = days  # the form shows it straight away
	return record


def employee_on_trash(doc, method=None):
	"""The notice period goes with the employee (it would block deleting the employee)."""
	for name in frappe.get_all(DOCTYPE, filters={"employee": doc.name}, pluck="name"):
		frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)


@frappe.whitelist()
def get_notice_period(employee: str):
	"""Employee > Notice Period tab."""
	frappe.has_permission("Employee", "read", employee, throw=True)
	return frappe.db.get_value(
		DOCTYPE,
		{"employee": employee},
		["name", "notice_days", "effective_from", "source", "remarks", "modified"],
		as_dict=True,
	)


# ---------------------------------------------------------------------- permissions
def is_hr(user):
	return user == "Administrator" or bool(HR_ROLES & set(frappe.get_roles(user)))


def own_employees(user):
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name") if user != "Guest" else []


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if is_hr(user):
		return ""
	employees = own_employees(user)
	if not employees:
		return "1=0"
	values = ", ".join(frappe.db.escape(e) for e in employees)
	return f"`tab{DOCTYPE}`.`employee` in ({values})"


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if is_hr(user):
		return True
	return doc.employee in own_employees(user)


# ---------------------------------------------------------------------- after_migrate
def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)
	# a Single's field default is not stored by itself: save 30 once, never over HR's value
	if not default_saved():
		frappe.db.set_single_value("HR Settings", SETTINGS_FIELD, DEFAULT_NOTICE_DAYS)

"""Create User from Employee: same as ERPNext's create_user, but allowed for HR Managers
without giving them access to the User doctype."""

import frappe
from frappe import _
from frappe.permissions import add_user_permission
from frappe.utils import cint, validate_email_address

from alantech_erp.setup.access import FULL_ACCESS_DESIGNATIONS

CREATOR_ROLES = {"System Manager", "HR Manager"}


@frappe.whitelist()
def create_user(employee: str, email: str | None = None, create_user_permission: int = 0) -> str:
	if not CREATOR_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Only HR Managers can create users for employees."), frappe.PermissionError)

	emp = frappe.get_doc("Employee", employee)
	emp.check_permission("write")
	if emp.user_id:
		frappe.throw(_("Employee {0} already has a linked user").format(emp.name))
	if not email:
		frappe.throw(_("Email is required to create a user"))

	email = validate_email_address(email, True)
	if frappe.db.exists("User", email):
		frappe.throw(_("User {0} already exists. Select it in the User ID field instead.").format(email))

	names = (emp.employee_name or "").split(" ")
	first_name, middle_name, last_name = names[0], "", ""
	if len(names) >= 3:
		middle_name, last_name = names[1], " ".join(names[2:])
	elif len(names) == 2:
		last_name = names[1]

	user = frappe.new_doc("User")
	user.update(
		{
			"email": email,
			"enabled": 1,
			"first_name": first_name,
			"middle_name": middle_name,
			"last_name": last_name,
			"gender": emp.gender,
			"birth_date": emp.date_of_birth,
			"phone": emp.cell_number,
			"bio": emp.bio,
			# welcome email only when an outgoing account exists (avoids the Email Account error)
			"send_welcome_email": 1
			if frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1})
			else 0,
		}
	)
	emp.db_set("user_id", email)
	user.append_roles("Employee")
	user.insert(ignore_permissions=True)  # the one real difference from ERPNext

	# MD / HR Manager / HR Executive must see all employees: never restrict them to their own record
	restrict = cint(create_user_permission) and emp.designation not in FULL_ACCESS_DESIGNATIONS

	emp.user_id = user.name
	emp.create_user_permission = 1 if restrict else 0
	emp.save()  # also applies the designation's role profile (org_structure.sync_user_role_profile)

	if restrict:
		add_user_permission("Employee", emp.name, user.name)
		add_user_permission("Company", emp.company, user.name)

	return user.name
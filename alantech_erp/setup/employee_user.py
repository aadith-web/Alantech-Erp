"""Create User from Employee: same as ERPNext's create_user, but allowed for HR Managers
without giving them access to the User doctype.

hooks.py:
    override_whitelisted_methods = {
        "erpnext.setup.doctype.employee.employee.create_user": "alantech_erp.setup.employee_user.create_user",
    }
    doc_events = {"Employee": {
        "before_insert": "alantech_erp.setup.employee_user.employee_before_insert",
        "after_insert": "alantech_erp.setup.employee_user.employee_after_insert",
    }}
"""

import frappe
from frappe import _
from frappe.permissions import add_user_permission
from frappe.utils import cint, validate_email_address

from alantech_erp.setup import approvers
from alantech_erp.setup.access import FULL_ACCESS_DESIGNATIONS, FULL_ACCESS_ROLES

# who may use Employee > Create User
CREATOR_ROLES = {"System Manager", "HR Manager"}


@frappe.whitelist()
def create_user(employee: str, email: str | None = None, create_user_permission: int = 0) -> str:
	if not CREATOR_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Only HR Managers can create users for employees."), frappe.PermissionError)

	emp = frappe.get_doc("Employee", employee)
	emp.check_permission("write")
	if emp.get("user_id"):
		frappe.throw(_("Employee {0} already has a linked user").format(emp.name))
	if not email:
		frappe.throw(_("Email is required to create a user"))

	email = validate_email_address(email, True)
	if frappe.db.exists("User", email):
		frappe.throw(_("User {0} already exists. Select it in the User ID field instead.").format(email))

	first_name, middle_name, last_name = split_name(emp.get("employee_name"))

	user = frappe.new_doc("User")
	user.update(
		{
			"email": email,
			"enabled": 1,
			"first_name": first_name,
			"middle_name": middle_name,
			"last_name": last_name,
			"gender": emp.get("gender"),
			"birth_date": emp.get("date_of_birth"),
			"phone": emp.get("cell_number"),
			"bio": emp.get("bio"),
			# welcome email only when an outgoing account exists (avoids the Email Account error)
			"send_welcome_email": 1 if outgoing_email_configured() else 0,
		}
	)
	emp.db_set("user_id", email)
	user.append("roles", {"role": "Employee"})
	user.insert(ignore_permissions=True)  # the one real difference from ERPNext

	# first decision by designation (MD / HR Manager / HR Executive are never restricted)
	restrict = bool(cint(create_user_permission)) and emp.get("designation") not in FULL_ACCESS_DESIGNATIONS

	emp.set("user_id", user.name)
	emp.set("create_user_permission", 1 if restrict else 0)
	emp.save()  # also applies the designation's role profile (org_structure.sync_user_role_profile)
	# user_id was already written by db_set above, so the save did not see it change
	approvers.user_changed(emp, None)

	# second decision by role, now that the role profile has been applied
	if restrict and has_full_access_role(user.name):
		restrict = False
		emp.db_set("create_user_permission", 0)

	if restrict:
		add_user_permission("Employee", emp.name, user.name, ignore_permissions=True)
		add_user_permission("Company", emp.get("company"), user.name, ignore_permissions=True)

	assert user.name is not None
	return user.name


def split_name(full_name):
	"""Same split as ERPNext: 'A' / 'A B' / 'A B C D' -> first, middle, last."""
	names = str(full_name or "").split()
	if not names:
		return "", "", ""
	if len(names) >= 3:
		return names[0], names[1], " ".join(names[2:])
	if len(names) == 2:
		return names[0], "", names[1]
	return names[0], "", ""


def has_full_access_role(user):
	frappe.clear_cache(user=user)
	return bool(FULL_ACCESS_ROLES & set(frappe.get_roles(user)))


def outgoing_email_configured():
	return bool(frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}))


# ---------------------------------------------------------------------- Employee doc_events
# Every employee with an email gets a user, whether added in the form or by Data Import, ticked
# "Create User Automatically" or not. ERPNext's own after_insert would call its create_user, which
# needs User create permission, so the request is taken over here and done with ours.


def employee_email(doc):
	return doc.get("prefered_email") or doc.get("company_email") or doc.get("personal_email")


def employee_before_insert(doc, method=None):
	if not doc.get("user_id") and employee_email(doc):
		doc.flags.alt_create_user = True
		doc.create_user_automatically = 0  # keeps ERPNext's after_insert out of it


def employee_after_insert(doc, method=None):
	if not doc.flags.pop("alt_create_user", None):
		return
	if auto_create_user(doc):
		doc.db_set("create_user_automatically", 1, update_modified=False)
		doc.reload()


def auto_create_user(doc):
	"""Create and link the user, or say why not. Never fails the employee save or import row:
	everything create_user would refuse is checked first."""
	email = employee_email(doc)
	reason = None
	if not CREATOR_ROLES & set(frappe.get_roles()):
		reason = _("only HR Managers can create users")
	elif not validate_email_address(email):
		reason = _("{0} is not a valid email").format(email)
	elif frappe.db.exists("User", email):
		linked = frappe.db.get_value("Employee", {"user_id": email, "name": ["!=", doc.name]}, "name")
		if linked:
			reason = _("{0} is already the user of {1}").format(email, linked)
		else:  # a user without an employee (e.g. made before the employee): link it
			doc.db_set("user_id", email)
			doc.reload()
			doc.save(ignore_permissions=True)  # role profile, approvers, user permissions
			approvers.user_changed(doc, None)
			return True
	if reason:
		frappe.msgprint(
			_("No user created for {0}: {1}.").format(doc.employee_name or doc.name, reason),
			indicator="orange",
			alert=True,
		)
		return False
	create_user(doc.name, email=email, create_user_permission=doc.get("create_user_permission"))
	return True


def create_missing_users():
	"""One-off / after_migrate: users for existing active employees that have an email."""
	created, skipped = [], []
	for name in frappe.get_all(
		"Employee", filters={"status": "Active", "user_id": ["is", "not set"]}, pluck="name", order_by="creation asc"
	):
		emp = frappe.get_doc("Employee", name)
		if not employee_email(emp):
			continue
		(created if auto_create_user(emp) else skipped).append(f"{emp.get("employee_name")} <{employee_email(emp)}>")
		frappe.db.commit()
	return created, skipped

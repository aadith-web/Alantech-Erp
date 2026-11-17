# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR can import employees (Employee list > Menu > Import).

The Import dialog (Frappe v16 data_import_dialog.js) is a Data Import form, and Frappe grants the
Data Import doctype to System Manager only. An HR Manager has import rights on Employee, yet the
dialog stayed empty and the page showed "Sorry! You are not permitted to view this page".

    execute()  after_migrate (hooks.py). Create-only Custom DocPerm rows on Data Import (a rule HR
               already changed is kept):
                   HR Manager, HR User   read / write / create
               Import logs are read through the Data Import (get_import_logs checks it), so Data
               Import Log needs no rule.

    Scope (hooks.py permission_query_conditions / has_permission): a user without System Manager
    sees and opens only imports into doctypes they may import themselves (Employee for HR), never
    a System Manager's import of e.g. invoices. Frappe itself refuses an import into a doctype the
    user has no import right on (DataImport.validate_doctype).
"""

import frappe

DOCTYPE = "Data Import"
ROLES = ("HR Manager", "HR User")
RIGHTS = ("read", "write", "create")
UNRESTRICTED_ROLES = {"System Manager"}


# ---------------------------------------------------------------------- after_migrate
def execute():
	from frappe.permissions import add_permission

	for role in ROLES:
		if not frappe.db.exists("Role", role):
			continue
		key = {"parent": DOCTYPE, "role": role, "permlevel": 0, "if_owner": 0}
		if frappe.db.exists("Custom DocPerm", key):
			continue
		# copies the standard System Manager rule to Custom DocPerm first when there is none yet
		add_permission(DOCTYPE, role, 0, "read")
		frappe.db.set_value("Custom DocPerm", key, {right: 1 for right in RIGHTS})
		frappe.clear_cache(doctype=DOCTYPE)


# ---------------------------------------------------------------------- scope
def is_unrestricted(user):
	return user == "Administrator" or bool(UNRESTRICTED_ROLES & set(frappe.get_roles(user)))


def importable_doctypes(user):
	"""Doctypes of existing imports that `user` may import into."""
	used = frappe.get_all(DOCTYPE, pluck="reference_doctype", distinct=True, ignore_permissions=True)
	return sorted(d for d in set(used) if d and frappe.has_permission(d, "import", user=user))


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if is_unrestricted(user):
		return ""
	doctypes = importable_doctypes(user)
	if not doctypes:
		return "1=0"
	values = ", ".join(frappe.db.escape(d) for d in doctypes)
	return f"`tabData Import`.`reference_doctype` in ({values})"


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if is_unrestricted(user) or not doc.get("reference_doctype"):
		return True  # a new import picks its doctype later; validate checks it on save
	return bool(frappe.has_permission(doc.reference_doctype, "import", user=user))

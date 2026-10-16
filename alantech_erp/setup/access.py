"""Access by designation (organisation structure AIS-MS-TP-01).

* Managing Director: every page (System Manager).
* HR Manager and HR Executive: full Frappe HR access (HR Manager + HR User).
* These designations see all employees: no Employee User Permission is created for them.
"""

import frappe

# Role profile -> roles added on top of the ones org_structure.py gives it
EXTRA_PROFILE_ROLES = {
    "ALT Managing Director": ["System Manager", "HR Manager", "HR User"],
    "ALT HR Manager": ["HR Manager", "HR User"],
    "ALT HR Executive": ["HR Manager", "HR User"],
}

# Designations that must see every employee (no "own record only" restriction)
FULL_ACCESS_DESIGNATIONS = {"Managing Director", "HR Manager", "HR Executive"}


# ---------------------------------------------------------------------- after_migrate
def extend_role_profiles():
    """Runs BEFORE org_structure.setup_if_ready: adds the extra roles to its ROLE_PROFILES
    in memory, so each profile is saved once (a second save hits the Role Profile lock)."""
    from alantech_erp import org_structure

    for profile, roles in EXTRA_PROFILE_ROLES.items():
        current = org_structure.ROLE_PROFILES.setdefault(profile, [])
        for role in roles:
            if role not in current:
                current.append(role)


def execute():
    """Runs AFTER org_structure: remove the 'own record only' restriction for full-access designations."""
    for emp in frappe.get_all(
        "Employee",
        filters={"designation": ["in", list(FULL_ACCESS_DESIGNATIONS)]},
        fields=["name", "user_id", "create_user_permission"],
    ):
        if emp.create_user_permission:
            frappe.db.set_value("Employee", emp.name, "create_user_permission", 0, update_modified=False)
        _remove_employee_restriction(emp.user_id)
    frappe.db.commit()


def _remove_employee_restriction(user):
    if not user:
        return
    for name in frappe.get_all("User Permission", filters={"user": user, "allow": "Employee"}, pluck="name"):
        frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)


# ---------------------------------------------------------------------- Employee doc_events
def employee_validate(doc, method=None):
    """Full-access designations never get the 'own employee record only' restriction."""
    if doc.designation in FULL_ACCESS_DESIGNATIONS:
        doc.create_user_permission = 0


def employee_on_update(doc, method=None):
    if doc.designation in FULL_ACCESS_DESIGNATIONS:
        _remove_employee_restriction(doc.user_id)

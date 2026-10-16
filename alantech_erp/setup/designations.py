"""Designations added after the organisation chart (AIS-MS-TP-01).

Runs on every `bench migrate`, after org_structure.setup_if_ready (see after_migrate in hooks.py).
Safe to re-run: existing designations are updated, never duplicated.
"""

import frappe

# (designation, reports to designation, default department, role profile)
EXTRA_DESIGNATIONS = [
    ("RO Operator", "Aftersales Coordinator", "Aftersales", "ALT Shop Floor"),
]


def execute():
    company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
    if not company:
        return  # fresh site: nothing to attach departments to yet
    if not frappe.get_meta("Designation").has_field("alt_reports_to"):
        return  # org_structure has not created its Designation fields yet

    for desig, reports_to, dept, profile in EXTRA_DESIGNATIONS:
        if not frappe.db.exists("Designation", desig):
            frappe.get_doc({"doctype": "Designation", "designation_name": desig}).insert(ignore_permissions=True)

        frappe.db.set_value("Designation", desig, {
            "alt_reports_to": reports_to if frappe.db.exists("Designation", reports_to) else None,
            "alt_default_department": frappe.db.get_value(
                "Department", {"department_name": dept, "company": company}, "name"),
            "alt_role_profile": profile if frappe.db.exists("Role Profile", profile) else None,
        }, update_modified=False)

    frappe.db.commit()

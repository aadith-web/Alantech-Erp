"""Employee validations: one employee per Employee Number within a company."""

import frappe
from frappe import _


def validate_unique_employee(doc, method=None):
    """Employee.validate: block a second employee with the same Employee Number in the same company."""
    if not doc.employee_number:
        return
    doc.employee_number = doc.employee_number.strip()

    duplicate = frappe.db.get_value(
        "Employee",
        {
            "employee_number": doc.employee_number,
            "company": doc.company,
            "name": ["!=", doc.name or ""],
        },
        ["name", "employee_name"],
        as_dict=True,
    )
    if duplicate:
        frappe.throw(
            _(
                "Employee Number {0} already belongs to {1} ({2}). "
                "To change this employee, use Data Import with Import Type "
                "'Update Existing Records' and ID {2}."
            ).format(
                frappe.bold(doc.employee_number),
                frappe.bold(duplicate.employee_name),
                duplicate.name,
            ),
            frappe.DuplicateEntryError,
            title=_("Duplicate Employee"),
        )

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


# Employee Numbers run E001, E002, ... E132; a new employee without one gets the next.
EMPLOYEE_NUMBER_PREFIX = "E"
EMPLOYEE_NUMBER_DIGITS = 3


def set_employee_number(doc, method=None):
    """Employee.before_insert: fill a blank Employee Number with the next E### number."""
    if (doc.employee_number or "").strip():
        return
    doc.employee_number = next_employee_number()


def next_employee_number():
    """Highest E<digits> Employee Number + 1. Rows inserted earlier in the same Data Import
    are in the same transaction, so each row sees the one before it."""
    last = frappe.db.sql(
        """select max(cast(substring(employee_number, %(start)s) as unsigned))
        from `tabEmployee` where employee_number regexp %(pattern)s""",
        {"start": len(EMPLOYEE_NUMBER_PREFIX) + 1, "pattern": f"^{EMPLOYEE_NUMBER_PREFIX}[0-9]+$"},
    )[0][0]
    return f"{EMPLOYEE_NUMBER_PREFIX}{(last or 0) + 1:0{EMPLOYEE_NUMBER_DIGITS}d}"


def fill_missing_employee_numbers():
    """One-off: numbers for existing employees without one, oldest first."""
    filled = []
    for name in frappe.get_all(
        "Employee", filters={"employee_number": ["is", "not set"]}, pluck="name", order_by="creation asc"
    ):
        number = next_employee_number()
        frappe.db.set_value("Employee", name, "employee_number", number, update_modified=False)
        filled.append(f"{name}: {number}")
    frappe.db.commit()
    return filled

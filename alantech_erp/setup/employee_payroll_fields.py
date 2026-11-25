"""Employee fields needed before the first payroll ("Employee Mandatory Fields", part 2).

ClickUp: https://app.clickup.com/t/14yr2e57mhp (parent: https://app.clickup.com/t/14yr2e56b2e)

Part 1 (fields needed to create an employee) is employee_validation.REQUIRED_ON_CREATE. Part 2
fields may be added after the employee is created, but payroll is refused without them:

- Salary Mode, PAN Number, Grade, Payroll Cost Center, Holiday List, PF / Gratuity Reference Date,
  Confirmation Date (always)
- Bank Name, Bank Branch, Bank A/C No. and IFSC Code (when Salary Mode is Bank; either IFSC field)
- Contract End Date (when Employment Type is Contract)

Checked on submit of a Salary Structure Assignment and of a Payroll Entry (all its employees in
one message), and on a Salary Slip made by hand (slips of a Payroll Entry were checked there).
Confirmation Date is filled from Date of Joining + Probation Period (months) when left blank, and
the dates are checked against each other, in setup/employee_dates.py.

Hooked in hooks.py: doc_events (Employee, Salary Structure Assignment, Payroll Entry, Salary Slip)
and after_migrate (execute: custom fields + import template). Tests skip the check unless
frappe.flags.alt_check_payroll_fields is set, like REQUIRED_ON_CREATE.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

CONTRACT_EMPLOYMENT_TYPE = "Contract"
BANK_SALARY_MODE = "Bank"

CUSTOM_FIELDS = {
    "Employee": [
        {
            "fieldname": "alt_bank_branch",
            "label": "Bank Branch",
            "fieldtype": "Data",
            "insert_after": "bank_name",
            "depends_on": "eval:doc.salary_mode == 'Bank'",
        },
        {
            "fieldname": "alt_pf_gratuity_reference_date",
            "label": "PF / Gratuity Reference Date",
            "fieldtype": "Date",
            "insert_after": "payroll_cost_center",
            "description": "Date PF and gratuity service is counted from.",
        },
        {
            "fieldname": "alt_probation_period",
            "label": "Probation Period (Months)",
            "fieldtype": "Int",
            "non_negative": 1,
            "insert_after": "scheduled_confirmation_date",
            "description": "Confirmation Date = Date of Joining + these months (filled and kept in step). Leave blank to enter the Confirmation Date yourself.",
        },
    ],
}

# always needed before payroll
PAYROLL_REQUIRED = (
    "salary_mode",
    "pan_number",
    "grade",
    "payroll_cost_center",
    "holiday_list",
    "alt_pf_gratuity_reference_date",
    "final_confirmation_date",
)
BANK_REQUIRED = ("bank_name", "alt_bank_branch", "bank_ac_no")
IFSC_FIELDS = ("ifsc_code", "alt_ifsc_code")  # HRMS field and the older custom one; either is enough

# Part 1 fields ticked by "Select Mandatory" in the Employee import template (both emails: one is
# enough, see employee_validation.validate_required_on_create)
IMPORT_TEMPLATE_FIELDS = ("company_email", "personal_email")


def execute():
    """after_migrate: custom fields, and every field needed to create an employee in the template."""
    from alantech_erp.setup.employee_validation import REQUIRED_ON_CREATE

    create_custom_fields(CUSTOM_FIELDS, update=True)
    for fieldname in REQUIRED_ON_CREATE + IMPORT_TEMPLATE_FIELDS:
        make_property_setter(
            "Employee", fieldname, "in_import_template", 1, "Check", validate_fields_for_doctype=False
        )


def missing_payroll_fields(employee):
    """Labels of the payroll fields `employee` (doc, dict or name) has not filled."""
    if isinstance(employee, str):
        employee = frappe.get_doc("Employee", employee)
    meta = frappe.get_meta("Employee")
    filled = lambda field: bool(str(employee.get(field) or "").strip())  # noqa: E731

    fields = list(PAYROLL_REQUIRED)
    if employee.get("salary_mode") == BANK_SALARY_MODE:
        fields += BANK_REQUIRED
    if employee.get("employment_type") == CONTRACT_EMPLOYMENT_TYPE:
        fields.append("contract_end_date")
    missing = [_(meta.get_label(field)) for field in fields if not filled(field)]
    if employee.get("salary_mode") == BANK_SALARY_MODE and not any(filled(f) for f in IFSC_FIELDS):
        missing.append(_("IFSC Code"))
    return missing


@frappe.whitelist()
def get_missing_payroll_fields(employee: str):
    """Employee form: the fields still needed before the first payroll."""
    frappe.has_permission("Employee", "read", employee, throw=True)
    return missing_payroll_fields(employee)


class PayrollFieldsMissingError(frappe.ValidationError):
    pass


def check_employees(employees, action):
    """Refuse `action` when any of `employees` misses payroll fields; one line per employee."""
    if frappe.flags.in_test and not frappe.flags.alt_check_payroll_fields:
        return
    lines = []
    for employee in dict.fromkeys(e for e in employees if e):
        missing = missing_payroll_fields(employee)
        if missing:
            name = frappe.db.get_value("Employee", employee, "employee_name") or employee
            lines.append(f"<li>{frappe.bold(name)} ({employee}): {', '.join(missing)}</li>")
    if lines:
        frappe.throw(
            _("Fill these in the Employee record before {0}:").format(action) + f"<ul>{''.join(lines)}</ul>",
            PayrollFieldsMissingError,
            title=_("Employee Details Missing for Payroll"),
        )


def salary_structure_assignment_before_submit(doc, method=None):
    check_employees([doc.employee], _("assigning a salary structure"))


def payroll_entry_before_submit(doc, method=None):
    check_employees([row.employee for row in doc.get("employees") or []], _("running payroll"))


def salary_slip_validate(doc, method=None):
    """Hand-made slips only, when new; Payroll Entry slips were checked on its submit."""
    if doc.is_new() and not doc.get("payroll_entry"):
        check_employees([doc.employee], _("creating a salary slip"))

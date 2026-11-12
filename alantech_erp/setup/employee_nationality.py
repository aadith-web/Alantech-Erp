"""Employee Nationality (Citizen) mandatory; Aadhaar and PAN mandatory for Indian nationals.

ClickUp: https://app.clickup.com/t/14yr2e57r7h (Nationality) and
https://app.clickup.com/t/14yr2e57r7k (Aadhaar / PAN); parent https://app.clickup.com/t/14yr2e56cak

- Custom field Nationality (alt_nationality, Link Country) on the Overview tab after Date of Birth.
- Form: marked mandatory (red *) for new and existing employees, so an employee is not saved from
  the form without it (public/js/employee.js).
- Server (Employee.validate): a new employee is refused without it (form, Data Import, API), and a
  saved Nationality cannot be cleared: "Citizen is required. Please select Nationality."
  Employees saved before this rule may still be saved by the system (promotion, transfer, user
  linking, org structure) until HR fills it; the form asks for it on the next edit.
- Ticked in the Employee import template (in_import_template).

Nationality India (validate_indian_ids):
- Aadhaar Number (alt_aadhaar_number, Overview tab after Nationality) and PAN Number (standard
  field, Salary tab) are mandatory: red * on the form (mandatory_depends_on) and refused on the
  server with "Aadhaar Number and PAN Number are required when Nationality is India. Missing: ...".
  Other nationalities: both optional.
- Checked for new employees and when Nationality, Aadhaar or PAN changes, so system saves of older
  records are not blocked.
- Format (any nationality, new or changed values): Aadhaar 12 digits, not starting with 0 or 1 (spaces
  removed); PAN 5 letters, 4 digits, 1 letter (upper-cased), e.g. ABCDE1234F.
- Aadhaar unique across employees (any company, any status): "Aadhaar Number ... already belongs
  to <name> (<ID>)." Checked for new or changed values, like employee_validation's emails.

Hooked in hooks.py: Employee validate (validate_nationality, validate_indian_ids) and
after_migrate (execute).
Tests skip the server check unless frappe.flags.alt_check_employee_required is set, like
employee_validation.validate_required_on_create.
"""

import re

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

FIELD = "alt_nationality"
INDIA = "India"
AADHAAR_FIELD = "alt_aadhaar_number"
PAN_FIELD = "pan_number"
INDIA_CONDITION = f"eval:doc.{FIELD} == '{INDIA}'"
AADHAAR_PATTERN = re.compile(r"^[2-9][0-9]{11}$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

CUSTOM_FIELDS = {
    "Employee": [
        {
            "fieldname": FIELD,
            "label": "Nationality",
            "fieldtype": "Link",
            "options": "Country",
            "insert_after": "date_of_birth",
            "description": "Country the employee is a citizen of.",
            "in_standard_filter": 1,
        },
        {
            "fieldname": AADHAAR_FIELD,
            "label": "Aadhaar Number",
            "fieldtype": "Data",
            "insert_after": FIELD,
            "mandatory_depends_on": INDIA_CONDITION,
            "description": "12 digits. Mandatory when Nationality is India.",
        },
    ],
}


def execute():
    """after_migrate: the field, ticked in the Employee import template."""
    create_custom_fields(CUSTOM_FIELDS, update=True)
    for field in (FIELD, AADHAAR_FIELD, PAN_FIELD):
        make_property_setter("Employee", field, "in_import_template", 1, "Check", validate_fields_for_doctype=False)
    make_property_setter(
        "Employee", PAN_FIELD, "mandatory_depends_on", INDIA_CONDITION, "Code", validate_fields_for_doctype=False
    )


def validate_nationality(doc, method=None):
    """Employee.validate: Nationality needed on a new employee and never cleared once set."""
    if frappe.flags.in_test and not frappe.flags.alt_check_employee_required:
        return
    if (doc.get(FIELD) or "").strip():
        return
    before = None if doc.is_new() else doc.get_doc_before_save()
    if doc.is_new() or (before and before.get(FIELD)):
        frappe.throw(
            _("Citizen is required. Please select Nationality."),
            frappe.MandatoryError,
            title=_("Missing Fields"),
        )


class InvalidIdentityNumberError(frappe.ValidationError):
    pass


def validate_indian_ids(doc, method=None):
    """Employee.validate: Aadhaar / PAN format, and both mandatory when Nationality is India."""
    aadhaar = re.sub(r"[\s-]", "", doc.get(AADHAAR_FIELD) or "")
    pan = (doc.get(PAN_FIELD) or "").strip().upper()
    doc.set(AADHAAR_FIELD, aadhaar or None)
    doc.set(PAN_FIELD, pan or None)
    # new or changed values only: an old malformed value does not block system saves
    changed = lambda field: doc.is_new() or doc.has_value_changed(field)  # noqa: E731
    if aadhaar and changed(AADHAAR_FIELD) and not AADHAAR_PATTERN.match(aadhaar):
        frappe.throw(
            _("Aadhaar Number {0} is not valid: it has 12 digits and does not start with 0 or 1.").format(
                frappe.bold(aadhaar)
            ),
            InvalidIdentityNumberError,
            title=_("Invalid Aadhaar Number"),
        )
    if aadhaar and changed(AADHAAR_FIELD):
        duplicate = frappe.db.get_value(
            "Employee",
            {AADHAAR_FIELD: aadhaar, "name": ["!=", doc.name or ""]},
            ["name", "employee_name"],
            as_dict=True,
        )
        if duplicate:
            frappe.throw(
                _("Aadhaar Number {0} already belongs to {1} ({2}).").format(
                    frappe.bold(aadhaar), frappe.bold(duplicate.employee_name), duplicate.name
                ),
                frappe.DuplicateEntryError,
                title=_("Duplicate Aadhaar Number"),
            )
    if pan and changed(PAN_FIELD) and not PAN_PATTERN.match(pan):
        frappe.throw(
            _("PAN Number {0} is not valid: 5 letters, 4 digits and 1 letter, e.g. ABCDE1234F.").format(
                frappe.bold(pan)
            ),
            InvalidIdentityNumberError,
            title=_("Invalid PAN Number"),
        )

    if frappe.flags.in_test and not frappe.flags.alt_check_employee_required:
        return
    if doc.get(FIELD) != INDIA:
        return
    if not any(changed(f) for f in (FIELD, AADHAAR_FIELD, PAN_FIELD)):
        return
    meta = frappe.get_meta("Employee")
    missing = [_(meta.get_label(f)) for f in (AADHAAR_FIELD, PAN_FIELD) if not doc.get(f)]
    if missing:
        frappe.throw(
            _("Aadhaar Number and PAN Number are required when Nationality is India. Missing: {0}").format(
                ", ".join(frappe.bold(m) for m in missing)
            ),
            frappe.MandatoryError,
            title=_("Missing Fields"),
        )

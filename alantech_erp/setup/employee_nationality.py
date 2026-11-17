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
- Format (any nationality, new or changed values): the Document module's rules
  (document_number.clean_number): Aadhaar 12 digits, not starting with 0 or 1, with a valid
  Verhoeff check digit, stored in groups of four like the documents ("2345 6789 0124"); PAN 5 letters (4th = holder type, e.g. P),
  4 digits, 1 letter, upper-cased, e.g. ABCPE1234F.
- Kept equal to the employee's Aadhaar / PAN documents (alantech/doctype/document/employee_numbers.py).
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

from alantech_erp.alantech.doctype.document.document_number import clean_number

FIELD = "alt_nationality"
INDIA = "India"
AADHAAR_FIELD = "alt_aadhaar_number"
PAN_FIELD = "pan_number"
INDIA_CONDITION = f"eval:doc.{FIELD} == '{INDIA}'"

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


def format_aadhaar(value):
    """Aadhaar the way the Employee and the Aadhaar documents store it: "2345 6789 0124".
    Anything that is not 12 digits is left as typed (trimmed), for the format check to report."""
    digits = re.sub(r"[\s\-./]", "", value or "")
    if re.fullmatch(r"[0-9]{12}", digits):
        return f"{digits[:4]} {digits[4:8]} {digits[8:]}"
    return (value or "").strip()


def check_identity_number(field, value, employee=None):
    """Aadhaar / PAN value (compact) for `employee`: the Document module's rules (Verhoeff check
    digit, PAN holder letter), so a number accepted here is accepted on the documents too
    (alantech/doctype/document/employee_numbers.py keeps them equal); Aadhaar unique."""
    fmt = "Aadhaar" if field == AADHAAR_FIELD else "PAN"
    _value, error = clean_number(fmt, value, frappe._dict(number_format=fmt))
    if error:
        frappe.throw(error, InvalidIdentityNumberError, title=_("Invalid {0} Number").format(fmt))
    if field != AADHAAR_FIELD:
        return
    # stored "2345 6789 0124"; an older record may still have the digits only
    value = format_aadhaar(value)
    duplicate = frappe.db.get_value(
        "Employee",
        {AADHAAR_FIELD: ["in", [value, value.replace(" ", "")]], "name": ["!=", employee or ""]},
        ["name", "employee_name"],
        as_dict=True,
    )
    if duplicate:
        frappe.throw(
            _("Aadhaar Number {0} already belongs to {1} ({2}).").format(
                frappe.bold(value), frappe.bold(duplicate.employee_name), duplicate.name
            ),
            frappe.DuplicateEntryError,
            title=_("Duplicate Aadhaar Number"),
        )


def validate_indian_ids(doc, method=None):
    """Employee.validate: Aadhaar / PAN format, and both mandatory when Nationality is India."""
    aadhaar = format_aadhaar(doc.get(AADHAAR_FIELD))
    pan = (doc.get(PAN_FIELD) or "").strip().upper()
    doc.set(AADHAAR_FIELD, aadhaar or None)
    doc.set(PAN_FIELD, pan or None)
    # new or changed values only: an old malformed value does not block system saves
    changed = lambda field: doc.is_new() or doc.has_value_changed(field)  # noqa: E731
    for field in (AADHAAR_FIELD, PAN_FIELD):
        if doc.get(field) and changed(field):
            check_identity_number(field, doc.get(field), doc.name)

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

"""Custom fields on Employee: bank and family details, and the Documents section.
Employee Number as a column in the Employee and User lists.

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run:
existing fields are updated, never duplicated.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

EMPLOYEE_FIELDS = {
    "Employee": [
        # Overview tab, below Company Details: list of this employee's documents
        {
            "fieldname": "alt_documents_section",
            "label": "Documents",
            "fieldtype": "Section Break",
            "insert_after": "grade",
        },
        {
            "fieldname": "alt_documents_html",
            "label": "Documents",
            "fieldtype": "HTML",
            "insert_after": "alt_documents_section",
        },
        # Personal details tab
        {
            "fieldname": "alt_father_name",
            "label": "Father Name",
            "fieldtype": "Data",
            "insert_after": "marital_status",
        },
        # Salary / bank section, right after Bank A/C No.
        {
            "fieldname": "alt_bank_account_holder",
            "label": "Account Holder Name",
            "fieldtype": "Data",
            "insert_after": "bank_ac_no",
        },
        {
            "fieldname": "alt_ifsc_code",
            "label": "IFSC Code",
            "fieldtype": "Data",
            "length": 11,
            "insert_after": "alt_bank_account_holder",
        },
        {
            "fieldname": "alt_bank_account_type",
            "label": "Bank Account Type",
            "fieldtype": "Select",
            "options": "\nSavings\nCurrent",
            "insert_after": "alt_ifsc_code",
        },
    ],
    # copied from the linked Employee (see sync_user_employee_number)
    "User": [
        {
            "fieldname": "alt_employee_number",
            "label": "Employee Number",
            "fieldtype": "Data",
            "read_only": 1,
            "no_copy": 1,
            "in_list_view": 1,
            "in_standard_filter": 1,
            "insert_after": "username",
        },
    ],
}


def execute():
    create_custom_fields(EMPLOYEE_FIELDS, update=True)
    show_employee_number_in_list()
    # untick to add the employee without a user (employee_user.employee_before_insert)
    make_property_setter(
        "Employee", "create_user_automatically", "default", "1", "Text", validate_fields_for_doctype=False
    )
    # Mobile with a country code picker; numbers checked per country (employee_validation.validate_mobile_number)
    make_property_setter("Employee", "cell_number", "fieldtype", "Phone", "Select", validate_fields_for_doctype=False)
    make_property_setter("Employee", "cell_number", "options", "", "Text", validate_fields_for_doctype=False)
    # fill_user_employee_numbers() is not run here: Role Profile jobs started by this migrate
    # update the same users in parallel. Employee.on_update keeps the numbers in step.


def show_employee_number_in_list(doc=None, method=None):
    """Employee form and list: Employee Number shown, as a column and filter, and searchable in
    Employee links. Also HR Settings.on_update: with "Employee Naming By" = Naming Series, HRMS
    hides the field on every HR Settings save."""
    make_property_setter("Employee", "employee_number", "hidden", 0, "Check", validate_fields_for_doctype=False)
    # unique and never changed once saved (employee_validation.py)
    make_property_setter("Employee", "employee_number", "set_only_once", 1, "Check", validate_fields_for_doctype=False)
    for prop in ("in_list_view", "in_standard_filter"):
        make_property_setter("Employee", "employee_number", prop, 1, "Check", validate_fields_for_doctype=False)
    search_fields = frappe.get_meta("Employee").search_fields or "employee_name"
    if "employee_number" not in [f.strip() for f in search_fields.split(",")]:
        make_property_setter(
            "Employee", None, "search_fields", f"{search_fields},employee_number", "Data", for_doctype=True
        )


def sync_user_employee_number(doc, method=None):
    """Employee.on_update: keep User.alt_employee_number equal to the linked employee's number."""
    before = doc.get_doc_before_save()
    old_user = before.user_id if before else None
    if old_user and old_user != doc.user_id and frappe.db.exists("User", old_user):
        frappe.db.set_value("User", old_user, "alt_employee_number", None, update_modified=False)
    if doc.user_id and frappe.db.exists("User", doc.user_id):
        frappe.db.set_value("User", doc.user_id, "alt_employee_number", doc.employee_number, update_modified=False)


def fill_user_employee_numbers():
    """One-off (bench execute): users whose Employee Number is out of date."""
    frappe.db.sql(
        """update `tabUser` u join `tabEmployee` e on e.user_id = u.name
        set u.alt_employee_number = e.employee_number
        where not (u.alt_employee_number <=> e.employee_number)"""
    )

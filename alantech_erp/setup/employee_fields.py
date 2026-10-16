"""Custom fields on Employee for the Alantech employee import (bank and family details).

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run:
existing fields are updated, never duplicated.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

EMPLOYEE_FIELDS = {
    "Employee": [
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
    ]
}


def execute():
    create_custom_fields(EMPLOYEE_FIELDS, update=True)

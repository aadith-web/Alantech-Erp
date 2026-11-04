"""Custom fields on Stock Entry: the employee and Employee Uniform Issue a Material Issue was made for
(employee_uniform_issue.make_stock_entry), to trace and filter uniform stock movements.

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

STOCK_ENTRY_FIELDS = {
    "Stock Entry": [
        {
            "fieldname": "alt_employee_uniform_issue",
            "label": "Employee Uniform Issue",
            "fieldtype": "Link",
            "options": "Employee Uniform Issue",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
            "depends_on": "alt_employee_uniform_issue",
            "insert_after": "stock_entry_type",
        },
        {
            "fieldname": "alt_employee",
            "label": "Employee",
            "fieldtype": "Link",
            "options": "Employee",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
            "depends_on": "alt_employee",
            "insert_after": "alt_employee_uniform_issue",
        },
    ]
}


def execute():
    create_custom_fields(STOCK_ENTRY_FIELDS, update=True)

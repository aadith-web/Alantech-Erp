"""Custom fields on Asset Repair for damage found when an employee returns an asset.

Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run.
Asset Repair is the place to track and report asset issues: filter or group its list /
report view by Responsible Employee.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ASSET_REPAIR_FIELDS = {
    "Asset Repair": [
        {
            "fieldname": "alt_responsible_employee",
            "label": "Responsible Employee",
            "fieldtype": "Link",
            "options": "Employee",
            "insert_after": "asset_name",
            "in_standard_filter": 1,
            "in_list_view": 1,
            "description": "Employee who held the asset when the damage was found",
        },
        {
            "fieldname": "alt_responsible_employee_name",
            "label": "Responsible Employee Name",
            "fieldtype": "Data",
            "fetch_from": "alt_responsible_employee.employee_name",
            "read_only": 1,
            "depends_on": "alt_responsible_employee",
            "insert_after": "alt_responsible_employee",
        },
        {
            "fieldname": "alt_employee_asset_handover",
            "label": "Employee Asset Handover",
            "fieldtype": "Link",
            "options": "Employee Asset Handover",
            "read_only": 1,
            "no_copy": 1,
            "depends_on": "alt_employee_asset_handover",
            "insert_after": "alt_responsible_employee_name",
        },
    ]
}


def execute():
    create_custom_fields(ASSET_REPAIR_FIELDS, update=True)

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


# Warranty on the Asset, shown on each Employee Asset Handover row (ClickUp 14yr2e58k7e); ERPNext's
# Asset has insurance fields but no warranty.
ASSET_WARRANTY_FIELDS = {
    "Asset": [
        # picked as years + months with the Warranty picker (public/js/asset.js, an HTML field); the
        # Years / Months fields hold the values (hidden), Warranty keeps the period as text for the
        # handover rows and reports (setup/asset_warranty.py)
        {
            "fieldname": "alt_warranty_picker",
            "label": "Warranty",
            "fieldtype": "HTML",
            "insert_after": "available_for_use_date",
        },
        {
            "fieldname": "alt_warranty_years",
            "label": "Warranty (Years)",
            "fieldtype": "Select",
            "options": "\n" + "\n".join(str(n) for n in range(1, 31)),
            "insert_after": "alt_warranty_picker",
            "allow_on_submit": 1,
            "hidden": 1,
        },
        {
            "fieldname": "alt_warranty_months",
            "label": "Warranty (Months)",
            "fieldtype": "Select",
            "options": "\n" + "\n".join(str(n) for n in range(1, 12)),
            "insert_after": "alt_warranty_years",
            "allow_on_submit": 1,
            "hidden": 1,
        },
        {
            "fieldname": "alt_warranty",
            "label": "Warranty",
            "fieldtype": "Data",
            "insert_after": "alt_warranty_months",
            "read_only": 1,
            "allow_on_submit": 1,
            "hidden": 1,
        },
        {
            "fieldname": "alt_warranty_expiry_date",
            "label": "Warranty Expiry Date",
            "fieldtype": "Date",
            "insert_after": "alt_warranty",
            "allow_on_submit": 1,
            "read_only_depends_on": "eval:doc.alt_warranty_years || doc.alt_warranty_months",
            "description": "Purchase Date + Warranty. Enter it yourself only when no Warranty years / months are picked.",
            "in_standard_filter": 1,
        },
    ]
}


def execute():
    create_custom_fields(ASSET_REPAIR_FIELDS, update=True)
    create_custom_fields(ASSET_WARRANTY_FIELDS, update=True)

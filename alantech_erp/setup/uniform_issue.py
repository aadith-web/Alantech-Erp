"""Employee Uniform Issue setup. Runs on every `bench migrate` (see after_migrate in hooks.py). Safe to re-run.

* Custom fields on Stock Entry: the employee and Employee Uniform Issue a Material Issue was made for
  (employee_uniform_issue.make_stock_entry), to trace and filter uniform stock movements.
* Select access the uniform issue roles need to fill the form and the register's filters
  (the doctype's own permissions are in its JSON: HR User / Stock User prepare, HR Manager /
  Stock Manager submit, cancel and amend).
* Links to the doctype and the register in the HR (Tenure) and Stock sidebars.
"""

import frappe
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

# (doctype, role): the role may pick these in link fields ("select" only, no read of the records).
# HR roles pick the source warehouse; stock roles pick the employee, and the department in the register.
SELECT_ACCESS = (
    ("Warehouse", "HR User"),
    ("Employee", "Stock User"),
    ("Department", "Stock User"),
    ("Department", "Stock Manager"),
)

# Module (sidebar) -> links added at its end, under a "Uniforms" heading
SIDEBAR_MODULES = ("Tenure", "Stock")
SIDEBAR_ITEMS = (
    {"type": "Section Break", "label": "Uniforms", "icon": "shirt", "indent": 1, "collapsible": 1},
    {"type": "Link", "label": "Employee Uniform Issue", "link_type": "DocType",
     "link_to": "Employee Uniform Issue", "child": 1},
    {"type": "Link", "label": "Employee Uniform Issue Register", "link_type": "Report",
     "link_to": "Employee Uniform Issue Register", "child": 1},
    {"type": "Link", "label": "Uniform Issue Settings", "link_type": "DocType",
     "link_to": "Uniform Issue Settings", "child": 1},
)


def execute():
    create_custom_fields(STOCK_ENTRY_FIELDS, update=True)
    add_select_access()
    add_sidebar_links()


def add_select_access():
    """Create-only: a role that already has a rule on the doctype keeps it as it is."""
    from frappe.permissions import add_permission

    for doctype, role in SELECT_ACCESS:
        if not frappe.db.exists("Role", role):
            continue
        if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}):
            continue
        add_permission(doctype, role, 0, "select")
        # a new Custom DocPerm row has read on by default: select only
        frappe.db.set_value(
            "Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}, "read", 0
        )
        frappe.clear_cache(doctype=doctype)


def add_sidebar_links():
    """Appended to the site's layer of each sidebar; rows already there (even hidden ones) are skipped,
    so a site that hid or moved them keeps its arrangement."""
    from frappe.desk.doctype.custom_sidebar.custom_sidebar import add_site_sidebar_item

    for module in SIDEBAR_MODULES:
        if not frappe.db.exists("Module Def", module):
            continue
        for item in SIDEBAR_ITEMS:
            add_site_sidebar_item(module, dict(item))

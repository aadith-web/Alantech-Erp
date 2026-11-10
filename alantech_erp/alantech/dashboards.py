"""Doctype dashboard overrides for HR doctypes (override_doctype_dashboards in hooks.py)."""

from frappe import _

# shown on the Employee form's Connections; each links to the employee by its `employee` field
EMPLOYEE_LINKS = ["Employee Uniform Issue", "Employee Asset Handover"]


def employee(data):
    """Employee Connections: Uniform Issues, Asset Handovers and Company Policy."""
    transactions = data.setdefault("transactions", [])
    linked = {doctype for group in transactions for doctype in group.get("items", [])}
    items = [doctype for doctype in EMPLOYEE_LINKS if doctype not in linked]
    if items:
        transactions.append({"label": _("Uniform & Assets"), "items": items})

    if data.get("fieldname", "employee") != "employee":
        for doctype in items:
            data.setdefault("non_standard_fieldnames", {})[doctype] = "employee"

    # Company Policy has no employee link, so it is a plain card that opens the policy list
    if "Company Policy" not in linked:
        transactions.append({"label": _("Policies"), "items": ["Company Policy"]})
        data.setdefault("non_standard_fieldnames", {})["Company Policy"] = "name"
    return data

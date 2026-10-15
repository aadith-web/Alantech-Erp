"""
Alantech organisation structure and role management (source: AIS-MS-TP-01, version 01, 02-09-2024).

Place at:  apps/alantech_erp/alantech_erp/org_structure.py

Run (safe to re-run; it updates instead of duplicating):
    bench --site alantech.localhost execute alantech_erp.org_structure.execute

What it creates
    * Custom roles for Alantech-specific work (BOQ / proposals, design)
    * Role Profiles (one bundle of standard ERPNext/HRMS roles per job family)
    * Departments for the company
    * Designations, each with: reports-to designation, default department, role profile
      (stored in custom fields alt_reports_to, alt_default_department, alt_role_profile)

Employee hooks (wire them in hooks.py, see bottom of file)
    * On save, an employee with a designation gets the default department and,
      if exactly one active employee holds the parent designation, the Reports To.
    * If the employee has a linked User with no role profile yet, the designation's
      role profile is applied to that user.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
CUSTOM_ROLES = [
    "Proposal Engineer",  # technical-commercial quotes, BOQ (custom doctypes come later)
    "Design Engineer",  # BOM / drawings ownership, design approvals in workflows
]

EMP = ["Employee"]
APPROVER = ["Leave Approver", "Expense Approver"]

ROLE_PROFILES = {
    # Management
    "ALT Managing Director": [
        "Accounts Manager", "Sales Manager", "Purchase Manager", "Stock Manager",
        "Manufacturing Manager", "Projects Manager", "HR Manager", "Quality Manager",
        "Auditor", "Report Manager", "Analytics", *APPROVER, *EMP,
    ],
    # Finance & purchase
    "ALT Finance Manager": [
        "Accounts Manager", "Accounts User", "Purchase Manager", "Auditor",
        "Report Manager", "Analytics", *APPROVER, *EMP,
    ],
    "ALT Accounts Head": ["Accounts Manager", "Accounts User", "Report Manager", "Leave Approver", *EMP],
    "ALT Accounts Executive": ["Accounts User", *EMP],
    "ALT Internal Auditor": ["Auditor", "Report Manager", "Leave Approver", *EMP],
    "ALT Audit Executive": ["Auditor", *EMP],
    "ALT Purchase Manager": [
        "Purchase Manager", "Purchase Master Manager", "Purchase User", "Stock User",
        "Leave Approver", *EMP,
    ],
    "ALT Purchase Executive": ["Purchase User", "Stock User", *EMP],
    # Sales & marketing
    "ALT Sales Head": [
        "Sales Manager", "Sales Master Manager", "Sales User", "Projects User",
        "Report Manager", *APPROVER, *EMP,
    ],
    "ALT Sales Manager": ["Sales Manager", "Sales User", "Leave Approver", *EMP],
    "ALT Sales Engineer": ["Sales User", *EMP],
    "ALT Proposal Engineer": ["Sales User", "Proposal Engineer", *EMP],
    "ALT Marketing Manager": ["Sales Manager", "Sales User", "Leave Approver", *EMP],
    "ALT Marketing Executive": ["Sales User", *EMP],
    # HR
    "ALT HR Manager": ["HR Manager", "HR User", *APPROVER, *EMP],
    "ALT HR Executive": ["HR User", *EMP],
    # Operations
    "ALT Operations Manager": [
        "Manufacturing Manager", "Projects Manager", "Stock Manager", "Quality Manager",
        "Maintenance Manager", "Item Manager", "Purchase User", "Report Manager",
        *APPROVER, *EMP,
    ],
    "ALT Design Head": [
        "Manufacturing User", "Item Manager", "Projects User", "Design Engineer",
        "Leave Approver", *EMP,
    ],
    "ALT Design Engineer": ["Manufacturing User", "Projects User", "Design Engineer", *EMP],
    "ALT Engineering Lead": ["Manufacturing User", "Projects User", "Leave Approver", *EMP],
    "ALT Engineer": ["Manufacturing User", "Projects User", *EMP],
    "ALT Quality Controller": ["Quality Manager", "Stock User", "Manufacturing User", "Leave Approver", *EMP],
    "ALT Jr Quality Controller": ["Stock User", "Manufacturing User", *EMP],
    "ALT Aftersales Coordinator": [
        "Maintenance Manager", "Maintenance User", "Support Team", "Sales User",
        "Projects User", "Leave Approver", *EMP,
    ],
    "ALT Service Engineer": ["Maintenance User", "Support Team", *EMP],
    # Production
    "ALT Production Manager": [
        "Manufacturing Manager", "Manufacturing User", "Stock User", "Projects User",
        *APPROVER, *EMP,
    ],
    "ALT Production Supervisor": ["Manufacturing User", "Stock User", "Leave Approver", *EMP],
    "ALT Store Keeper": ["Stock Manager", "Stock User", "Leave Approver", *EMP],
    "ALT Store Assistant": ["Stock User", *EMP],
    "ALT Logistics Executive": ["Stock User", "Delivery User", *EMP],
    # Shop floor (usually no ERP login; employee self-service only)
    "ALT Shop Floor": [*EMP],
}

# ---------------------------------------------------------------------------
# Departments (flat under "All Departments"; hierarchy lives in reports-to)
# ---------------------------------------------------------------------------
DEPARTMENTS = [
    "Management", "Accounts", "Internal Audit", "Purchase", "Sales", "Marketing",
    "Human Resources", "Operations", "Design", "Process Design", "Automation",
    "Quality Control", "Aftersales", "Production", "Electrical", "Stores", "Logistics",
]

# ---------------------------------------------------------------------------
# Designations: (designation, reports to, default department, role profile)
# ---------------------------------------------------------------------------
DESIGNATIONS = [
    # Management team
    ("Managing Director", None, "Management", "ALT Managing Director"),
    ("Finance Manager", "Managing Director", "Accounts", "ALT Finance Manager"),
    ("Sales Head", "Managing Director", "Sales", "ALT Sales Head"),
    ("HR Manager", "Managing Director", "Human Resources", "ALT HR Manager"),
    ("Operations Manager", "Managing Director", "Operations", "ALT Operations Manager"),
    ("Marketing Manager", "Managing Director", "Marketing", "ALT Marketing Manager"),
    ("HR Executive", "HR Manager", "Human Resources", "ALT HR Executive"),
    ("Marketing Executive", "Marketing Manager", "Marketing", "ALT Marketing Executive"),
    # Finance & purchase team
    ("Internal Auditor", "Finance Manager", "Internal Audit", "ALT Internal Auditor"),
    ("Audit Executive", "Internal Auditor", "Internal Audit", "ALT Audit Executive"),
    ("Accounts Head", "Finance Manager", "Accounts", "ALT Accounts Head"),
    ("Accounts Executive", "Accounts Head", "Accounts", "ALT Accounts Executive"),
    ("Purchase Manager", "Finance Manager", "Purchase", "ALT Purchase Manager"),
    ("Purchase Executive", "Purchase Manager", "Purchase", "ALT Purchase Executive"),
    # Sales team (regions Kerala / Bangalore / Hyderabad / UAE are Territories, not designations)
    ("Sales Manager", "Sales Head", "Sales", "ALT Sales Manager"),
    ("Sales Engineer", "Sales Manager", "Sales", "ALT Sales Engineer"),
    ("Proposal Engineer", "Sales Manager", "Sales", "ALT Proposal Engineer"),
    # Operations team
    ("Production Manager", "Operations Manager", "Production", "ALT Production Manager"),
    ("Design Head", "Operations Manager", "Design", "ALT Design Head"),
    ("Design Engineer", "Design Head", "Design", "ALT Design Engineer"),
    ("Process Design Engineer", "Operations Manager", "Process Design", "ALT Engineering Lead"),
    ("Jr. Process Design Engineer", "Process Design Engineer", "Process Design", "ALT Engineer"),
    ("Sr. Automation Engineer", "Operations Manager", "Automation", "ALT Engineering Lead"),
    ("Automation Engineer", "Sr. Automation Engineer", "Automation", "ALT Engineer"),
    ("Quality Controller", "Operations Manager", "Quality Control", "ALT Quality Controller"),
    ("Jr. Quality Controller", "Quality Controller", "Quality Control", "ALT Jr Quality Controller"),
    # Aftersales team
    ("Aftersales Coordinator", "Operations Manager", "Aftersales", "ALT Aftersales Coordinator"),
    ("Process Engineer", "Aftersales Coordinator", "Aftersales", "ALT Engineer"),
    ("Jr. Process Engineer", "Process Engineer", "Aftersales", "ALT Engineer"),
    ("Service Engineer", "Aftersales Coordinator", "Aftersales", "ALT Service Engineer"),
    ("Jr. Service Engineer", "Service Engineer", "Aftersales", "ALT Service Engineer"),
    # Production team
    ("Production Supervisor", "Production Manager", "Production", "ALT Production Supervisor"),
    ("Fabricator", "Production Supervisor", "Production", "ALT Shop Floor"),
    ("Machinist", "Production Supervisor", "Production", "ALT Shop Floor"),
    ("Turner", "Production Supervisor", "Production", "ALT Shop Floor"),
    ("Welder", "Production Supervisor", "Production", "ALT Shop Floor"),
    ("Fitter", "Production Supervisor", "Production", "ALT Shop Floor"),
    ("Helper", "Production Supervisor", "Production", "ALT Shop Floor"),
    ("Electrical Head", "Production Manager", "Electrical", "ALT Engineering Lead"),
    ("Electrician", "Electrical Head", "Electrical", "ALT Shop Floor"),
    ("Electrical Engineer", "Production Manager", "Electrical", "ALT Engineer"),
    ("Store Keeper", "Production Manager", "Stores", "ALT Store Keeper"),
    ("Store Assistant", "Store Keeper", "Stores", "ALT Store Assistant"),
    ("Logistics Executive", "Production Manager", "Logistics", "ALT Logistics Executive"),
]

CUSTOM_FIELDS = {
    "Designation": [
        {
            "fieldname": "alt_reports_to",
            "label": "Reports To (Designation)",
            "fieldtype": "Link",
            "options": "Designation",
            "insert_after": "designation_name",
        },
        {
            "fieldname": "alt_default_department",
            "label": "Default Department",
            "fieldtype": "Link",
            "options": "Department",
            "insert_after": "alt_reports_to",
        },
        {
            "fieldname": "alt_role_profile",
            "label": "Role Profile",
            "fieldtype": "Link",
            "options": "Role Profile",
            "insert_after": "alt_default_department",
        },
    ]
}


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def execute(company=None):
    company = company or frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
    if not company:
        frappe.throw("No Company found. Finish the setup wizard first.")
    print(f"Company: {company}")

    create_custom_fields(CUSTOM_FIELDS, update=True)
    _create_roles()
    missing = _create_role_profiles()
    dept_names = _create_departments(company)
    _create_designations(dept_names)
    frappe.db.commit()

    print(f"Roles: {len(CUSTOM_ROLES)} custom | Role profiles: {len(ROLE_PROFILES)} | "
          f"Departments: {len(DEPARTMENTS)} | Designations: {len(DESIGNATIONS)}")
    if missing:
        print("Skipped roles not present on this site:", ", ".join(sorted(missing)))


def _create_roles():
    for role in CUSTOM_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def _create_role_profiles():
    missing = set()
    for profile, roles in ROLE_PROFILES.items():
        valid = []
        for r in dict.fromkeys(roles):  # de-duplicate, keep order
            if frappe.db.exists("Role", r):
                valid.append(r)
            else:
                missing.add(r)
        if frappe.db.exists("Role Profile", profile):
            doc = frappe.get_doc("Role Profile", profile)
            doc.set("roles", [])
        else:
            doc = frappe.new_doc("Role Profile")
            doc.role_profile = profile
        for r in valid:
            doc.append("roles", {"role": r})
        doc.save(ignore_permissions=True)
    return missing


def _create_departments(company):
    root = frappe.db.get_value("Department", {"is_group": 1, "parent_department": ["in", ["", None]]}, "name") \
        or "All Departments"
    names = {}
    for dept in DEPARTMENTS:
        name = frappe.db.get_value("Department", {"department_name": dept, "company": company}, "name")
        if not name:
            doc = frappe.get_doc({
                "doctype": "Department",
                "department_name": dept,
                "company": company,
                "parent_department": root,
            }).insert(ignore_permissions=True)
            name = doc.name
        names[dept] = name
    return names


def _create_designations(dept_names):
    for desig, *_ in DESIGNATIONS:
        if not frappe.db.exists("Designation", desig):
            frappe.get_doc({"doctype": "Designation", "designation_name": desig}).insert(ignore_permissions=True)

    for desig, reports_to, dept, profile in DESIGNATIONS:
        frappe.db.set_value("Designation", desig, {
            "alt_reports_to": reports_to,
            "alt_default_department": dept_names.get(dept),
            "alt_role_profile": profile,
        }, update_modified=False)


# ---------------------------------------------------------------------------
# Employee hooks
# ---------------------------------------------------------------------------
def apply_designation_defaults(doc, method=None):
    """Employee.validate: fill department and reports_to from the designation when empty."""
    if not doc.designation:
        return
    parent_desig, dept = frappe.db.get_value(
        "Designation", doc.designation, ["alt_reports_to", "alt_default_department"]
    ) or (None, None)

    if not doc.department and dept and frappe.db.get_value("Department", dept, "company") == doc.company:
        doc.department = dept

    if not doc.reports_to and parent_desig:
        managers = frappe.get_all(
            "Employee",
            filters={"designation": parent_desig, "company": doc.company,
                     "status": "Active", "name": ["!=", doc.name or ""]},
            pluck="name",
            limit=2,
        )
        if len(managers) == 1:  # several (e.g. regional sales managers): leave for the user to pick
            doc.reports_to = managers[0]


def sync_user_role_profile(doc, method=None):
    """Employee.on_update: give the linked user the designation's role profile, never overriding one set by hand."""
    if not (doc.user_id and doc.designation) or doc.user_id in ("Administrator", "Guest"):
        return
    profile = frappe.db.get_value("Designation", doc.designation, "alt_role_profile")
    if not profile:
        return

    user = frappe.get_doc("User", doc.user_id)
    if user.meta.has_field("role_profiles"):  # newer Frappe: multiple role profiles per user
        if user.get("role_profiles"):
            return
        user.append("role_profiles", {"role_profile": profile})
    else:
        if user.get("role_profile_name"):
            return
        user.role_profile_name = profile
    user.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# hooks.py additions
# ---------------------------------------------------------------------------
# doc_events = {
#     "Employee": {
#         "validate": "alantech_erp.org_structure.apply_designation_defaults",
#         "on_update": "alantech_erp.org_structure.sync_user_role_profile",
#     }
# }
#
# fixtures += [
#     {"dt": "Role", "filters": [["name", "in", ["Proposal Engineer", "Design Engineer"]]]},
#     {"dt": "Role Profile", "filters": [["name", "like", "ALT %"]]},
#     {"dt": "Designation"},
#     {"dt": "Department"},
# ]

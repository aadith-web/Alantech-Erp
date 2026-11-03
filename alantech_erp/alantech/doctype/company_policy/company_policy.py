import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

# Roles allowed to publish, archive and edit published policies
MANAGER_ROLES = {"HR Manager", "HR User", "System Manager"}

# Roles that bypass employee-level filtering (they use normal role permissions)
PRIVILEGED_ROLES = {"HR Manager", "HR User", "System Manager"}


class CompanyPolicy(Document):
    def validate(self):
        self.policy_code = (self.policy_code or "").strip()
        self.policy_title = (self.policy_title or "").strip()
        self.version = (self.version or "").strip()
        self.validate_version()
        self.validate_category()
        self.validate_status_authorization()
        self.validate_applicability()
        if self.status == "Published":
            self.validate_publication()

    def validate_version(self):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,20}", self.version or ""):
            frappe.throw(
                _("Version may contain only letters, numbers, '.', '_' and '-' (max 20 characters).")
            )

    def validate_category(self):
        before = self.get_doc_before_save()
        if self.is_new() or (before and before.category != self.category):
            if not frappe.db.get_value("Policy Category", self.category, "enabled"):
                frappe.throw(_("Policy Category {0} is disabled.").format(self.category))

    def validate_status_authorization(self):
        is_manager = bool(MANAGER_ROLES & set(frappe.get_roles()))
        before = self.get_doc_before_save()
        old_status = before.status if before else "Draft"
        if {old_status, self.status} & {"Published", "Archived"} and not is_manager:
            frappe.throw(
                _("Only HR users can publish, archive or edit published policies."),
                frappe.PermissionError,
            )

    def validate_applicability(self):
        if self.applies_to_all:
            return
        for table, field in (
            ("applicable_departments", "department"),
            ("applicable_designations", "designation"),
            ("applicable_branches", "branch"),
        ):
            values = [row.get(field) for row in self.get(table)]
            if len(values) != len(set(values)):
                frappe.throw(_("Duplicate entries in {0}.").format(self.meta.get_label(table)))

    def validate_publication(self):
        if not self.effective_date:
            frappe.throw(_("Effective Date is required to publish."))
        if not self.policy_file:
            frappe.throw(_("Attach the policy file before publishing."))
        if not self.policy_file.startswith("/private/"):
            frappe.throw(_("The policy file must be a private file."))
        if not frappe.db.exists("File", {"file_url": self.policy_file}):
            frappe.throw(_("The attached policy file could not be found."))
        if not (self.applies_to_all or self.applicable_departments or self.applicable_designations or self.applicable_branches):
            frappe.throw(_("Select who the policy applies to, or tick Applies to All."))


# ---------------------------------------------------------------------------
# Employee access rules (HR-F11-2)
#
# An employee can read a policy only if ALL of these hold:
#   1. Status is Published
#   2. Effective Date is today or earlier
#   3. Applies to All is ticked, OR the policy has at least one applicability
#      row and every populated table (department, designation, branch)
#      contains the employee's value  (AND across tables, OR within a table)
# A policy with Applies to All unticked and all tables empty is visible to
# no employee. A user with no active linked Employee record sees nothing.
# ---------------------------------------------------------------------------

    def on_update(self):
        before = self.get_doc_before_save()
        just_published = self.status == "Published" and (not before or before.status != "Published")
        if just_published and getdate(self.effective_date) <= getdate(nowdate()):
            frappe.enqueue(
                "alantech_erp.alantech.doctype.company_policy.company_policy.notify_policy_published",
                policy=self.name,
                enqueue_after_commit=True,
            )
            
def _is_privileged(user):
    return user == "Administrator" or bool(PRIVILEGED_ROLES & set(frappe.get_roles(user)))


def _employee_context(user):
    return frappe.db.get_value(
        "Employee",
        {"user_id": user, "status": "Active"},
        ["department", "designation", "branch"],
        as_dict=True,
    )


def _child_clause(table, field, value):
    rows = f"select 1 from `tab{table}` t where t.parent = `tabCompany Policy`.name"
    if value:
        return (
            f"(not exists ({rows}) "
            f"or exists ({rows} and t.{field} = {frappe.db.escape(value)}))"
        )
    # Employee has no value for this field: only policies that don't restrict by it
    return f"not exists ({rows})"


def get_permission_query_conditions(user=None):
    user = user or frappe.session.user
    if _is_privileged(user):
        return ""

    emp = _employee_context(user)
    if not emp:
        return "1=0"

    parent = "t.parent = `tabCompany Policy`.name"
    any_rows = (
        f"(exists (select 1 from `tabCompany Policy Department` t where {parent}) "
        f"or exists (select 1 from `tabCompany Policy Designation` t where {parent}) "
        f"or exists (select 1 from `tabCompany Policy Branch` t where {parent}))"
    )

    return (
        "(`tabCompany Policy`.status = 'Published' "
        f"and `tabCompany Policy`.effective_date <= {frappe.db.escape(nowdate())} "
        "and (`tabCompany Policy`.applies_to_all = 1 or ("
        f"{any_rows} "
        f"and {_child_clause('Company Policy Department', 'department', emp.department)} "
        f"and {_child_clause('Company Policy Designation', 'designation', emp.designation)} "
        f"and {_child_clause('Company Policy Branch', 'branch', emp.branch)})))"
    )


def has_permission(doc, ptype=None, user=None, **kwargs):
    user = user or frappe.session.user
    if _is_privileged(user):
        return None  # leave HR roles to the normal role rules

    if ptype not in (None, "read", "select"):
        return False
    if doc.get("status") != "Published":
        return False
    if not doc.get("effective_date") or getdate(doc.get("effective_date")) > getdate():
        return False

    emp = _employee_context(user)
    if not emp:
        return False
    if doc.get("applies_to_all"):
        return True

    groups = (
        ([r.department for r in doc.get("applicable_departments") or []], emp.department),
        ([r.designation for r in doc.get("applicable_designations") or []], emp.designation),
        ([r.branch for r in doc.get("applicable_branches") or []], emp.branch),
    )
    if not any(values for values, _mine in groups):
        return False  # no audience configured: never visible
    return all((not values) or (mine in values) for values, mine in groups)

def notify_policy_published(policy):
    """Bell notification to every employee who may read this policy."""
    doc = frappe.get_doc("Company Policy", policy)
    users = frappe.get_all(
        "Employee",
        filters={"status": "Active", "user_id": ["is", "set"]},
        pluck="user_id",
    )
    for user in set(users):
        if not has_permission(doc, "read", user):
            continue
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "for_user": user,
                "type": "Alert",
                "subject": _("New policy published: {0} (v{1})").format(doc.policy_title, doc.version),
                "document_type": "Company Policy",
                "document_name": doc.name,
            }
        ).insert(ignore_permissions=True)
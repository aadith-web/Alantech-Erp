"""Unit tests for Company Policy (HR-F11-1/2/3/4).

Run on a throwaway test site only (never on the dev site): see the commands in the hand-off notes.
Employee department/designation/branch is supplied by patching `_employee_context`, so no Employee
records are needed. Every record created here is prefixed ZZT and removed in tearDownClass.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from alantech_erp.alantech.doctype.company_policy import company_policy as cp

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Policy Category",
    "Department",
    "Designation",
    "Branch",
    "Company Policy Department",
    "Company Policy Designation",
    "Company Policy Branch",
]

PFX = "ZZT"
EMP = "zzt_emp@example.com"
HRU = "zzt_hru@example.com"
HRM = "zzt_hrm@example.com"
SM = "zzt_sm@example.com"
USERS = ((EMP, "Employee"), (HRU, "HR User"), (HRM, "HR Manager"), (SM, "System Manager"))

CTX = "alantech_erp.alantech.doctype.company_policy.company_policy._employee_context"
DEPT, OTHER_DEPT = "ZZT Dept X", "ZZT Dept Other"
DESG, OTHER_DESG = "ZZT Desg Y", "ZZT Desg Other"
BRANCH, OTHER_BRANCH = "ZZT Branch Z", "ZZT Branch Other"

# code suffixes of the fixture policies created once for the whole class
ALL_FIXTURES = ["ALL", "DEPT", "DESG", "BRANCH", "COMBO", "NONE", "DRAFT", "ARCH", "FUTURE"]
DENIED_TO_EMPLOYEES = ["DRAFT", "ARCH", "FUTURE", "NONE"]
DUPLICATE = (frappe.DuplicateEntryError, frappe.UniqueValidationError)


def ctx(department=None, designation=None, branch=None):
    return frappe._dict(department=department, designation=designation, branch=branch)


def make_category(name, enabled=1):
    return frappe.get_doc(
        {"doctype": "Policy Category", "category_name": name, "enabled": enabled}
    ).insert(ignore_permissions=True)


def make_file(name, content, private=1):
    return frappe.get_doc(
        {"doctype": "File", "file_name": name, "content": content, "is_private": private}
    ).insert(ignore_permissions=True)


def make_user(email, role):
    user = frappe.get_doc(
        {"doctype": "User", "email": email, "first_name": PFX, "enabled": 1, "send_welcome_email": 0}
    ).insert(ignore_permissions=True)
    if role == "Employee":
        frappe.get_doc(
            {"doctype": "Has Role", "parent": email, "parenttype": "User", "parentfield": "roles", "role": role}
        ).insert(ignore_permissions=True)
    else:
        user.add_roles(role)
    frappe.clear_cache(user=email)

def make_policy(code, cat, file_url, **kw):
    data = {
        "doctype": "Company Policy",
        "policy_title": f"{PFX} Policy {code}",
        "policy_code": f"{PFX}-{code}",
        "category": cat,
        "version": "1.0",
        "effective_date": add_days(nowdate(), -1),
        "applies_to_all": 1,
        "policy_file": file_url,
        "status": "Published",
    }
    data.update(kw)
    doc = frappe.get_doc(data)
    doc.flags.ignore_links = True  # the test departments/designations/branches are not real records
    return doc


def cleanup():
    frappe.set_user("Administrator")
    frappe.db.delete("Notification Log", {"document_type": "Company Policy", "document_name": ["like", f"{PFX}-%"]})
    for doctype, filters in (
        ("Company Policy", {"name": ["like", f"{PFX}-%"]}),
        ("Policy Category", {"name": ["like", f"{PFX} %"]}),
        ("File", {"file_name": ["like", "zzt_%"]}),
    ):
        for name in frappe.get_all(doctype, filters=filters, pluck="name"):
            frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
    for email, _role in USERS:
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=1, ignore_permissions=True)
    frappe.db.delete("Version", {"ref_doctype": "Company Policy", "docname": ["like", f"{PFX}-%"]})
    frappe.db.delete(
        "Deleted Document",
        {"deleted_doctype": ["in", ["Company Policy", "Policy Category"]], "deleted_name": ["like", f"{PFX}%"]},
    )


class IntegrationTestCompanyPolicy(IntegrationTestCase):
    # ------------------------------------------------------------------ fixtures
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cleanup()
        cls.cat = make_category(f"{PFX} Cat").name
        cls.cat_off = make_category(f"{PFX} Cat Off", enabled=0).name
        cls.pfile = make_file("zzt_main.txt", "zzt main file").file_url
        cls.pubfile = make_file("zzt_public.txt", "zzt public file", private=0).file_url
        for email, role in USERS:
            make_user(email, role)

        def build(code, **kw):
            doc = make_policy(code, cls.cat, cls.pfile, **kw)
            doc.insert()
            return doc

        with patch.object(frappe, "enqueue"):
            build("ALL")
            build("DEPT", applies_to_all=0, applicable_departments=[{"department": DEPT}])
            build("DESG", applies_to_all=0, applicable_designations=[{"designation": DESG}])
            build("BRANCH", applies_to_all=0, applicable_branches=[{"branch": BRANCH}])
            build(
                "COMBO",
                applies_to_all=0,
                applicable_departments=[{"department": DEPT}],
                applicable_designations=[{"designation": DESG}],
            )
            # Published but with no audience at all (cannot be created through the controller)
            build("NONE", applies_to_all=0, status="Draft", policy_file=None)
            frappe.db.set_value("Company Policy", f"{PFX}-NONE", "status", "Published")
            build("DRAFT", status="Draft")
            archived = build("ARCH")
            archived.status = "Archived"
            archived.save()
            build("FUTURE", effective_date=add_days(nowdate(), 30))

    @classmethod
    def tearDownClass(cls):
        cleanup()
        super().tearDownClass()

    def setUp(self):
        frappe.set_user("Administrator")
        self.enqueue = patch.object(frappe, "enqueue").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        frappe.set_user("Administrator")

    def new(self, code, **kw):
        return make_policy(code, self.cat, self.pfile, **kw)

    def draft(self, code, **kw):
        kw.setdefault("status", "Draft")
        kw.setdefault("policy_file", None)
        return self.new(code, **kw)

    # ------------------------------------------------------------ basics (HR-F11-1)
    def test_status_defaults_to_draft(self):
        doc = frappe.get_doc(
            {
                "doctype": "Company Policy",
                "policy_title": "t",
                "policy_code": f"{PFX}-T-DEF",
                "category": self.cat,
                "version": "1.0",
                "effective_date": nowdate(),
                "applies_to_all": 1,
            }
        )
        self.assertEqual(doc.insert().status, "Draft")

    def test_name_is_policy_code(self):
        self.assertEqual(self.draft("T-NAME").insert().name, f"{PFX}-T-NAME")

    def test_duplicate_code_rejected(self):
        self.draft("T-DUP").insert()
        with self.assertRaises(DUPLICATE):
            self.draft("T-DUP").insert()

    def test_required_fields(self):
        for field in ("policy_title", "effective_date", "version", "category"):
            with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
                self.draft(f"T-REQ-{field}", **{field: None}).insert()

    def test_blank_title_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.draft("T-BLANK", policy_title="   ").insert()

    def test_version_format(self):
        for bad in ("v 1/2", "x" * 21, "1.0!", "   "):
            with self.subTest(version=bad), self.assertRaises(frappe.ValidationError):
                self.draft("T-VER", version=bad).insert()
        for good in ("1.0", "v2", "2026-01_A"):
            with self.subTest(version=good):
                self.assertEqual(self.draft(f"T-VER-{good}", version=good).insert().version, good)

    def test_version_is_trimmed(self):
        self.assertEqual(self.draft("T-TRIM", version=" 1.0 ").insert().version, "1.0")

    # ------------------------------------------------------------------ categories
    def test_disabled_category_rejected_for_new_policy(self):
        with self.assertRaises(frappe.ValidationError):
            self.draft("T-CAT", category=self.cat_off).insert()

    def test_changing_to_disabled_category_rejected(self):
        doc = self.draft("T-CAT3").insert()
        doc.category = self.cat_off
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_existing_policy_survives_category_being_disabled(self):
        doc = self.draft("T-CAT2").insert()
        frappe.db.set_value("Policy Category", self.cat, "enabled", 0)
        try:
            doc.reload()
            doc.summary = "edited"
            doc.save()  # category unchanged, so it must still save
        finally:
            frappe.db.set_value("Policy Category", self.cat, "enabled", 1)

    # ------------------------------------------------------------------ publication
    def test_publish_requires_file(self):
        with self.assertRaises(frappe.ValidationError):
            self.new("T-PUB1", policy_file=None).insert()

    def test_publish_rejects_public_file(self):
        with self.assertRaises(frappe.ValidationError):
            self.new("T-PUB2", policy_file=self.pubfile).insert()

    def test_publish_rejects_missing_file(self):
        with self.assertRaises(frappe.ValidationError):
            self.new("T-PUB3", policy_file="/private/files/zzt_does_not_exist.pdf").insert()

    def test_publish_requires_audience(self):
        with self.assertRaises(frappe.ValidationError):
            self.new("T-PUB4", applies_to_all=0).insert()

    def test_publish_valid_policy(self):
        self.assertEqual(self.new("T-PUB5").insert().status, "Published")

    def test_publish_with_one_table_is_enough(self):
        doc = self.new("T-PUB7", applies_to_all=0, applicable_branches=[{"branch": BRANCH}]).insert()
        self.assertEqual(doc.status, "Published")

    def test_future_effective_date_can_be_published(self):
        doc = self.new("T-PUB6", effective_date=add_days(nowdate(), 10)).insert()
        self.assertEqual(doc.status, "Published")

    def test_draft_does_not_need_a_file_or_audience(self):
        self.assertEqual(self.draft("T-DRAFT2", applies_to_all=0).insert().status, "Draft")

    def test_duplicate_applicability_rows_rejected(self):
        for field, key, value in (
            ("applicable_departments", "department", DEPT),
            ("applicable_designations", "designation", DESG),
            ("applicable_branches", "branch", BRANCH),
        ):
            with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
                self.draft(f"T-DUPROW-{key}", applies_to_all=0, **{field: [{key: value}, {key: value}]}).insert()

    def test_policy_file_is_private(self):
        self.assertTrue(self.pfile.startswith("/private/"))
        self.assertEqual(frappe.db.get_value("File", {"file_url": self.pfile}, "is_private"), 1)

    # ------------------------------------------------- who may change what (HR-F11-2)
    def test_hr_roles_pass_the_controller_permission_check(self):
        """Regression: the hook used to return None for HR roles, which Frappe treats as a denial."""
        for user in (HRU, HRM, SM):
            with self.subTest(user=user):
                new_doc = frappe.new_doc("Company Policy")
                self.assertTrue(frappe.has_permission("Company Policy", "write", doc=new_doc, user=user))
                self.assertTrue(frappe.has_permission("Company Policy", "create", doc=new_doc, user=user))
                self.assertIs(cp.has_permission(new_doc, "write", user), True)

    def test_hr_can_create_edit_publish_and_archive(self):
        for user, code in ((HRU, "T-HRU"), (HRM, "T-HRM"), (SM, "T-SM")):
            with self.subTest(user=user):
                frappe.set_user(user)
                doc = self.new(code).insert()  # created as Published
                doc.summary = "edited"
                doc.save()
                doc.status = "Archived"
                doc.save()
                frappe.set_user("Administrator")

    def test_hr_can_publish_a_draft(self):
        frappe.set_user(HRM)
        doc = self.draft("T-HRPUB").insert()
        doc.policy_file = self.pfile
        doc.status = "Published"
        doc.save()
        self.assertEqual(doc.status, "Published")

    def test_employee_has_no_write_create_or_delete(self):
        with patch(CTX, return_value=ctx(DEPT, DESG, BRANCH)):
            self.assertFalse(frappe.has_permission("Company Policy", "create", user=EMP))
            self.assertFalse(frappe.has_permission("Company Policy", "create", doc=frappe.new_doc("Company Policy"), user=EMP))
            for code in ("ALL", "DEPT", "DRAFT"):
                for ptype in ("write", "delete", "create"):
                    with self.subTest(policy=code, ptype=ptype):
                        self.assertFalse(frappe.has_permission("Company Policy", ptype, doc=f"{PFX}-{code}", user=EMP))

    def test_employee_cannot_create_through_the_api(self):
        frappe.set_user(EMP)
        with self.assertRaises(frappe.PermissionError):
            self.draft("T-EMP1").insert()

    def test_controller_blocks_employee_publishing_even_with_permissions_bypassed(self):
        frappe.set_user(EMP)
        doc = self.new("T-EMP2")
        doc.flags.ignore_permissions = True
        with self.assertRaises(frappe.PermissionError):
            doc.insert()

    def test_controller_blocks_employee_editing_a_published_policy(self):
        doc = frappe.get_doc("Company Policy", f"{PFX}-ALL")
        frappe.set_user(EMP)
        doc.summary = "tampered"
        doc.flags.ignore_permissions = True
        with self.assertRaises(frappe.PermissionError):
            doc.save()

    def test_controller_blocks_employee_archiving_and_publishing(self):
        for code, new_status in (("ALL", "Archived"), ("DRAFT", "Published")):
            with self.subTest(policy=code):
                frappe.set_user("Administrator")
                doc = frappe.get_doc("Company Policy", f"{PFX}-{code}")
                frappe.set_user(EMP)
                doc.status = new_status
                doc.flags.ignore_permissions = True
                with self.assertRaises(frappe.PermissionError):
                    doc.save()

    # ----------------------------------------------- visibility / applicability rules
    def visible(self, user, context):
        """Fixture policies this user sees; asserts the list query and the document check agree."""
        names = [f"{PFX}-{code}" for code in ALL_FIXTURES]
        with patch(CTX, return_value=context):
            listed = set(
                frappe.get_list("Company Policy", filters={"name": ["in", names]}, pluck="name", limit_page_length=0, user=user)
            )
            allowed = {n for n in names if frappe.has_permission("Company Policy", "read", doc=n, user=user)}
        self.assertEqual(listed, allowed, "get_list and has_permission disagree")
        return {n[len(PFX) + 1 :] for n in listed}

    def test_employee_visibility_rules(self):
        cases = {
            "all criteria match": (ctx(DEPT, DESG, BRANCH), {"ALL", "DEPT", "DESG", "BRANCH", "COMBO"}),
            "wrong department": (ctx(OTHER_DEPT, DESG, BRANCH), {"ALL", "DESG", "BRANCH"}),
            "wrong designation": (ctx(DEPT, OTHER_DESG, BRANCH), {"ALL", "DEPT", "BRANCH"}),
            "wrong branch": (ctx(DEPT, DESG, OTHER_BRANCH), {"ALL", "DEPT", "DESG", "COMBO"}),
            "department only": (ctx(DEPT, None, None), {"ALL", "DEPT"}),
            "no organisation info": (ctx(None, None, None), {"ALL"}),
            "no active employee record": (None, set()),
        }
        for label, (context, expected) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(self.visible(EMP, context), expected)

    def test_combined_criteria_use_and_across_tables(self):
        # COMBO needs department AND designation: one of the two is not enough
        self.assertNotIn("COMBO", self.visible(EMP, ctx(DEPT, OTHER_DESG, BRANCH)))
        self.assertNotIn("COMBO", self.visible(EMP, ctx(OTHER_DEPT, DESG, BRANCH)))
        self.assertIn("COMBO", self.visible(EMP, ctx(DEPT, DESG, None)))

    def test_hidden_states_are_never_visible_to_employees(self):
        seen = self.visible(EMP, ctx(DEPT, DESG, BRANCH))
        for code in DENIED_TO_EMPLOYEES:
            self.assertNotIn(code, seen)

    def test_policy_with_no_audience_is_visible_to_nobody(self):
        for context in (ctx(DEPT, DESG, BRANCH), ctx(None, None, None)):
            self.assertNotIn("NONE", self.visible(EMP, context))

    def test_policy_effective_today_is_visible(self):
        self.new("T-TODAY", effective_date=nowdate()).insert()
        with patch(CTX, return_value=ctx()):
            self.assertTrue(frappe.has_permission("Company Policy", "read", doc=f"{PFX}-T-TODAY", user=EMP))

    def test_hr_and_administrator_see_everything(self):
        for user in (HRU, HRM, SM, "Administrator"):
            with self.subTest(user=user):
                self.assertEqual(self.visible(user, None), set(ALL_FIXTURES))

    def test_query_conditions(self):
        self.assertEqual(cp.get_permission_query_conditions(HRU), "")
        self.assertEqual(cp.get_permission_query_conditions("Administrator"), "")
        with patch(CTX, return_value=None):
            self.assertEqual(cp.get_permission_query_conditions(EMP), "1=0")
        with patch(CTX, return_value=ctx(DEPT, DESG, BRANCH)):
            condition = cp.get_permission_query_conditions(EMP)
        self.assertIn("status = 'Published'", condition)
        self.assertIn("effective_date <=", condition)

    def test_direct_document_and_api_access_is_blocked(self):
        frappe.set_user(EMP)
        with patch(CTX, return_value=ctx(DEPT, DESG, BRANCH)):
            for code in DENIED_TO_EMPLOYEES:
                with self.subTest(policy=code):
                    with self.assertRaises(frappe.PermissionError):
                        frappe.get_doc("Company Policy", f"{PFX}-{code}").check_permission("read")
                    with self.assertRaises(frappe.PermissionError):
                        frappe.client.get("Company Policy", f"{PFX}-{code}")
            frappe.get_doc("Company Policy", f"{PFX}-ALL").check_permission("read")

    # ---------------------------------------- employee profile list (get_applicable_policies)
    def applicable(self, context):
        with patch("frappe.has_permission", return_value=True), patch("frappe.db.get_value", return_value=context):
            rows = cp.get_applicable_policies("HR-EMP-ZZT")
        return rows, {r["name"][len(PFX) + 1 :] for r in rows if r["name"].startswith(PFX)}

    def test_applicable_policies_follow_the_employee_shown(self):
        _rows, names = self.applicable(ctx(DEPT, DESG, BRANCH))
        self.assertEqual(names, {"ALL", "DEPT", "DESG", "BRANCH", "COMBO"})
        _rows, names = self.applicable(ctx(OTHER_DEPT, OTHER_DESG, OTHER_BRANCH))
        self.assertEqual(names, {"ALL"})
        _rows, names = self.applicable(ctx(None, None, None))
        self.assertEqual(names, {"ALL"})

    def test_applicable_policies_row_shape(self):
        rows, _names = self.applicable(ctx(DEPT, DESG, BRANCH))
        row = next(r for r in rows if r["name"] == f"{PFX}-ALL")
        for key in ("name", "policy_title", "policy_code", "version", "effective_date", "policy_file"):
            self.assertIn(key, row)

    def test_applicable_policies_empty_for_unknown_employee(self):
        rows, _names = self.applicable(None)
        self.assertEqual(rows, [])

    def test_applicable_policies_needs_read_access_to_the_employee(self):
        with patch("frappe.has_permission", side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                cp.get_applicable_policies("HR-EMP-ZZT")

    # ------------------------------------------------------- notification (HR-F11-4)
    def test_publishing_enqueues_a_notification(self):
        doc = self.new("T-N1").insert()
        self.enqueue.assert_called_once()
        self.assertEqual(self.enqueue.call_args.kwargs["policy"], doc.name)

    def test_no_notification_for_draft_future_or_resave(self):
        self.draft("T-N2").insert()
        self.new("T-N3", effective_date=add_days(nowdate(), 5)).insert()
        self.enqueue.assert_not_called()
        doc = self.new("T-N4").insert()
        self.enqueue.reset_mock()
        doc.summary = "edited"
        doc.save()
        self.enqueue.assert_not_called()

    def test_publishing_a_draft_enqueues_once(self):
        doc = self.draft("T-N5").insert()
        self.enqueue.assert_not_called()
        doc.policy_file = self.pfile
        doc.status = "Published"
        doc.save()
        self.enqueue.assert_called_once()

    def notified(self, code, context):
        real_get_all = frappe.get_all

        def fake_get_all(doctype, *args, **kwargs):
            if doctype == "Employee":
                return [EMP, EMP]  # one user listed twice: must be notified once
            return real_get_all(doctype, *args, **kwargs)

        with patch.object(frappe, "get_all", side_effect=fake_get_all), patch(CTX, return_value=context):
            cp.notify_policy_published(f"{PFX}-{code}")
        return frappe.get_all(
            "Notification Log",
            filters={"document_type": "Company Policy", "document_name": f"{PFX}-{code}", "for_user": EMP},
            fields=["subject"],
        )

    def test_eligible_employee_is_notified_once(self):
        logs = self.notified("ALL", ctx(DEPT, DESG, BRANCH))
        self.assertEqual(len(logs), 1)
        self.assertIn("New policy published", logs[0].subject)

    def test_ineligible_employee_is_not_notified(self):
        self.assertEqual(self.notified("DEPT", ctx(OTHER_DEPT, DESG, BRANCH)), [])

    # ----------------------------------------------------------------- file access
    def test_private_file_is_served_only_through_an_allowed_policy(self):
        from frappe.core.doctype.file.utils import find_file_by_url

        url = make_file("zzt_restricted.txt", "zzt restricted unique content").file_url
        self.assertTrue(url.startswith("/private/"))
        make_policy("T-FILE", self.cat, url, applies_to_all=0, applicable_departments=[{"department": DEPT}]).insert()
        cases = (
            ("eligible employee", EMP, ctx(DEPT, DESG, BRANCH), True),
            ("other-department employee", EMP, ctx(OTHER_DEPT, DESG, BRANCH), False),
            ("employee without organisation info", EMP, ctx(None, None, None), False),
            ("employee without employee record", EMP, None, False),
            ("HR User", HRU, None, True),
            ("Guest", "Guest", None, False),
        )
        for label, user, context, expected in cases:
            with self.subTest(case=label):
                frappe.set_user(user)
                with patch(CTX, return_value=context):
                    self.assertEqual(find_file_by_url(url) is not None, expected)
                frappe.set_user("Administrator")
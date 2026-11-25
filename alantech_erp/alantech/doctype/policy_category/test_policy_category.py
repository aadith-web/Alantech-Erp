"""Unit tests for Policy Category. Run on a test site only; records are prefixed ZZT and removed afterwards."""

import frappe
from frappe.tests import IntegrationTestCase

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []

DUPLICATE = (frappe.DuplicateEntryError, frappe.UniqueValidationError)
BLANK = (frappe.ValidationError, frappe.NameError)


def make(name, **kw):
    return frappe.get_doc({"doctype": "Policy Category", "category_name": name, **kw})


class IntegrationTestPolicyCategory(IntegrationTestCase):
    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        for name in frappe.get_all("Policy Category", filters={"name": ["like", "ZZT %"]}, pluck="name"):
            frappe.delete_doc("Policy Category", name, force=1, ignore_permissions=True)
        super().tearDownClass()

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_create_valid_category(self):
        doc = make("ZZT Valid", category_description="General policies").insert()
        self.assertEqual(doc.name, "ZZT Valid")
        self.assertEqual(doc.enabled, 1)

    def test_duplicate_name_rejected(self):
        make("ZZT Dup").insert()
        with self.assertRaises(DUPLICATE):
            make("ZZT Dup").insert()

    def test_blank_name_rejected(self):
        for bad in ("", "   "):
            with self.subTest(name=repr(bad)), self.assertRaises(BLANK):
                make(bad).insert()

    def test_name_is_trimmed(self):
        self.assertEqual(make("  ZZT Trim  ").insert().category_name, "ZZT Trim")

    def test_can_be_created_disabled(self):
        self.assertEqual(make("ZZT Off", enabled=0).insert().enabled, 0)

    def test_can_be_disabled_later(self):
        doc = make("ZZT Later").insert()
        doc.enabled = 0
        doc.save()
        self.assertEqual(frappe.db.get_value("Policy Category", "ZZT Later", "enabled"), 0)

    def test_permissions(self):
        for email, role in (("zzt_cat_hru@example.com", "HR User"), ("zzt_cat_emp@example.com", "Employee")):
            user = frappe.get_doc(
                {"doctype": "User", "email": email, "first_name": "ZZT", "enabled": 1, "send_welcome_email": 0}
            ).insert(ignore_permissions=True)
            user.add_roles(role)
        try:
            self.assertTrue(frappe.has_permission("Policy Category", "read", user="zzt_cat_hru@example.com"))
            self.assertFalse(frappe.has_permission("Policy Category", "write", user="zzt_cat_hru@example.com"))
            self.assertFalse(frappe.has_permission("Policy Category", "create", user="zzt_cat_hru@example.com"))
            self.assertFalse(frappe.has_permission("Policy Category", "read", user="zzt_cat_emp@example.com"))
        finally:
            for email in ("zzt_cat_hru@example.com", "zzt_cat_emp@example.com"):
                frappe.delete_doc("User", email, force=1, ignore_permissions=True)
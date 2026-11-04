import frappe
from frappe.tests import IntegrationTestCase


def make_category(name="ZZ Policy Cat", enabled=1):
    if frappe.db.exists("Policy Category", name):
        frappe.db.set_value("Policy Category", name, "enabled", enabled)
    else:
        frappe.get_doc({"doctype": "Policy Category", "category_name": name, "enabled": enabled}).insert()
    return name


def make_private_file(name="zz_policy_test.txt"):
    return frappe.get_doc(
        {"doctype": "File", "file_name": name, "content": "test", "is_private": 1}
    ).insert().file_url


def make_policy(**kw):
    data = {
        "doctype": "Company Policy",
        "policy_title": "ZZ Test Policy",
        "policy_code": "ZZ-TP-001",
        "category": make_category(),
        "version": "1.0",
        "effective_date": "2026-12-01",
        "applies_to_all": 1,
    }
    data.update(kw)
    return frappe.get_doc(data)


class IntegrationTestCompanyPolicy(IntegrationTestCase):
    def test_default_status_is_draft(self):
        self.assertEqual(make_policy().insert().status, "Draft")

    def test_duplicate_code_rejected(self):
        make_policy().insert()
        with self.assertRaises(frappe.DuplicateEntryError):
            make_policy().insert()

    def test_missing_required_fields(self):
        with self.assertRaises(frappe.MandatoryError):
            make_policy(version="").insert()

    def test_invalid_version_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            make_policy(version="v 1/2").insert()

    def test_disabled_category_rejected(self):
        cat = make_category("ZZ Disabled Cat", enabled=0)
        with self.assertRaises(frappe.ValidationError):
            make_policy(category=cat).insert()

    def test_publish_without_file_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            make_policy(status="Published").insert()

    def test_publish_without_audience_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            make_policy(
                status="Published", applies_to_all=0, policy_file=make_private_file()
            ).insert()

    def test_publish_valid_policy(self):
        doc = make_policy(status="Published", policy_file=make_private_file()).insert()
        self.assertEqual(doc.status, "Published")

    def test_duplicate_department_rows_rejected(self):
        dept = frappe.get_all("Department", pluck="name", limit=1)
        if not dept:
            self.skipTest("No Department records on this site")
        with self.assertRaises(frappe.ValidationError):
            make_policy(
                applies_to_all=0,
                departments=[{"department": dept[0]}, {"department": dept[0]}],
            ).insert()
# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Grade Level / Band / Sub Bands (setup/employee_grade.py, ClickUp 14yr2e586v1).

Covered:
- after_migrate: custom fields on Employee Grade, Sub Band master A to E.
- L3-B3 style grade with five sub band rows A to E and gross amounts; Default Salary Structure kept.
- Level + Band unique across grades; a sub band once per grade; Gross Amount above zero.
- get_gross_amount for the Create Salary Structure popup.
- Sub Band master (ClickUp 14yr2e586v2): Link not text, unique trimmed names, in-use bands cannot
  be deleted, HR Manager edits / HR User reads, HR Setup sidebar entry after Employee Grade.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_grade

Data: _Test-EG-* grades inside a savepoint rolled back after each test.
"""

import frappe

from alantech_erp.setup import employee_grade as eg

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

GROSS = {"A": 30000, "B": 32000, "C": 34000, "D": 36000, "E": 38500}


def make_grade(name, level=None, band=None, rows=None, **extra):
	return frappe.get_doc(
		{
			"doctype": "Employee Grade",
			"__newname": name,
			eg.LEVEL: level,
			eg.BAND: band,
			eg.SUB_BANDS: [{"sub_band": s, "gross_amount": g} for s, g in (rows or {}).items()],
			**extra,
		}
	).insert()


class TestEmployeeGrade(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		eg.execute()

	def setUp(self):
		frappe.db.savepoint("grade_test")
		self.addCleanup(frappe.db.rollback, save_point="grade_test")

	def test_setup_fields_and_sub_bands(self):
		meta = frappe.get_meta("Employee Grade")
		for field in (eg.LEVEL, eg.BAND, eg.SUB_BANDS, "default_salary_structure", "default_base_pay"):
			with self.subTest(field=field):
				self.assertTrue(meta.has_field(field))
		self.assertEqual(meta.get_field(eg.SUB_BANDS).options, "Employee Grade Sub Band")
		for sub_band in eg.DEFAULT_SUB_BANDS:
			self.assertTrue(frappe.db.exists("Sub Band", sub_band))

	def test_seed_does_not_recreate_deleted_sub_band(self):
		frappe.delete_doc("Sub Band", "E", force=True)
		eg.execute()
		self.assertFalse(frappe.db.exists("Sub Band", "E"))

	def test_grade_with_five_sub_bands(self):
		structure = frappe.db.get_value("Salary Structure", {"docstatus": 1}, "name")
		grade = make_grade(
			"_Test-EG-L3-B3", " _TL3 ", "_TB3", GROSS, default_salary_structure=structure, default_base_pay=38500
		)
		grade.reload()
		self.assertEqual((grade.get(eg.LEVEL), grade.get(eg.BAND)), ("_TL3", "_TB3"))
		self.assertEqual({r.sub_band: r.gross_amount for r in grade.get(eg.SUB_BANDS)}, GROSS)
		self.assertEqual(grade.default_salary_structure, structure)

	def test_level_and_band_unique(self):
		make_grade("_Test-EG-1", "_TL3", "_TB3")
		with self.assertRaises(eg.DuplicateGradeLevelError):
			make_grade("_Test-EG-2", "_TL3", "_TB3")
		make_grade("_Test-EG-3", "_TL3", "_TB4")  # same level, other band: allowed

	def test_resave_own_grade_allowed(self):
		grade = make_grade("_Test-EG-1", "_TL3", "_TB3", GROSS)
		grade.save()

	def test_sub_band_once_per_grade(self):
		grade = make_grade("_Test-EG-1", "_TL4", "_TB4", {"A": 40000})
		grade.append(eg.SUB_BANDS, {"sub_band": "A", "gross_amount": 41000})
		with self.assertRaises(eg.DuplicateSubBandError):
			grade.save()
		make_grade("_Test-EG-2", "_TL5", "_TB5", {"A": 50000})  # same sub band, other grade: allowed

	def test_gross_amount_above_zero(self):
		with self.assertRaises(eg.InvalidGrossAmountError):
			make_grade("_Test-EG-1", "_TL6", "_TB6", {"A": 0})

	def test_get_gross_amount(self):
		make_grade("_Test-EG-1", "_TL3", "_TB3", GROSS)
		self.assertEqual(eg.get_gross_amount("_Test-EG-1", "E"), 38500)
		self.assertIsNone(eg.get_gross_amount("_Test-EG-1", "Z"))

	def test_hooks(self):
		self.assertIn(
			"alantech_erp.setup.employee_grade.validate",
			frappe.get_hooks("doc_events")["Employee Grade"]["validate"],
		)
		self.assertIn("alantech_erp.setup.employee_grade.execute", frappe.get_hooks("after_migrate"))


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role} for role in roles])
	user.save(ignore_permissions=True)
	return email


class TestSubBandMaster(TestCase):
	"""Sub Band master (ClickUp 14yr2e586v2): a Link from a master, not typed text."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		eg.execute()

	def setUp(self):
		frappe.db.savepoint("sub_band_test")
		self.addCleanup(frappe.db.rollback, save_point="sub_band_test")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_sub_band_is_a_link_to_the_master(self):
		field = frappe.get_meta("Employee Grade Sub Band").get_field("sub_band")
		self.assertEqual((field.fieldtype, field.options, field.reqd), ("Link", "Sub Band", 1))
		with self.assertRaises(frappe.LinkValidationError):
			make_grade("_Test-EG-1", "_TL7", "_TB7", {"_Test-No-Such-Band": 1000})

	def test_name_trimmed_and_unique(self):
		doc = frappe.get_doc({"doctype": "Sub Band", "sub_band": " _Test-F "}).insert()
		self.assertEqual(doc.name, "_Test-F")
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Sub Band", "sub_band": "_Test-F"}).insert()

	def test_used_sub_band_cannot_be_deleted(self):
		make_grade("_Test-EG-1", "_TL8", "_TB8", {"A": 1000})
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Sub Band", "A")

	def test_permissions(self):
		hr_manager = make_user("_test-sb-hrm@example.com", ["HR Manager"])
		hr_user = make_user("_test-sb-hru@example.com", ["HR User"])
		for ptype in ("read", "create", "write", "delete"):
			self.assertTrue(frappe.has_permission("Sub Band", ptype, user=hr_manager), ptype)
		self.assertTrue(frappe.has_permission("Sub Band", "read", user=hr_user))
		for ptype in ("create", "write", "delete"):
			self.assertFalse(frappe.has_permission("Sub Band", ptype, user=hr_user), ptype)

	def sidebar_labels(self):
		from frappe.desk.doctype.sidebar.sidebar import resolve_sidebar

		frappe.clear_cache()
		return [item["label"] for item in resolve_sidebar(eg.SIDEBAR_MODULE, "Administrator").items]

	def wipe_site_layer(self):
		for name in frappe.get_all("Custom Sidebar", filters={"module": eg.SIDEBAR_MODULE}, pluck="name"):
			frappe.delete_doc("Custom Sidebar", name, force=True, ignore_permissions=True)

	def test_sidebar_sub_band_after_employee_grade(self):
		self.wipe_site_layer()
		eg.add_sub_band_to_sidebar()
		eg.add_sub_band_to_sidebar()
		labels = self.sidebar_labels()
		self.assertEqual(labels.count("Sub Band"), 1)
		self.assertEqual(labels[labels.index("Employee Grade") + 1], "Sub Band")
		self.assertEqual(labels[-1], "Settings")

	def test_sidebar_hr_arrangement_kept(self):
		from frappe.desk.doctype.custom_sidebar.custom_sidebar import _save_customization

		self.wipe_site_layer()
		_save_customization(eg.SIDEBAR_MODULE, [{"type": "Link", "link_type": "DocType", "link_to": "HR Settings"}], None)
		eg.add_sub_band_to_sidebar()
		layer = frappe.get_doc("Custom Sidebar", {"module": eg.SIDEBAR_MODULE, "user": ""})
		rows = [(row.link_to, row.added) for row in layer.sidebar_items]
		self.assertEqual(rows, [("HR Settings", 0), ("Sub Band", 1)])  # HR's row kept, Sub Band appended
		self.assertIn("Sub Band", self.sidebar_labels())

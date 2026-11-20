# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Grade master data from the PDF (ClickUp 14yr2e586v3): setup/data/employee_grades.csv and the
patch patches/v16/employee_grades_from_pdf.py.

Covered:
- The Data Import file, read with Frappe's Data Import parser, has the 10 grades of the PDF with
  the amounts of section 3 and the categories / ranges of section 2 (checked against a separate
  copy of the PDF tables below).
- The patch is create-only: it adds a missing grade and leaves existing ones as HR has them.
- Default Salary Structure only when the company has exactly one active structure.
- Minimum Gross above Maximum Gross refused; a sub band outside the range only warns.

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_employee_grades_import

Data: savepoint rolled back after each test.
"""

from unittest.mock import patch

import frappe

from alantech_erp.patches.v16 import employee_grades_from_pdf as loader
from alantech_erp.setup import employee_grade as eg

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

# PDF section 3: Level -> Band A to E
SECTION_3 = {
	"L1": (16000, 16500, 17000, 17500, 18000),
	"L2": (18000, 19000, 20000, 21000, 22000),
	"L3": (20000, 22000, 24000, 26000, 28000),
	"L4": (25000, 27500, 30000, 32500, 35000),
	"L5": (30000, 33750, 37500, 41250, 45000),
	"L6": (40000, 45000, 50000, 55000, 60000),
	"L7": (50000, 56250, 62500, 68750, 75000),
	"L8": (60000, 65000, 70000, 75000, 80000),
	"L9": (75000, 86250, 97500, 108750, 120000),
	"L10": (120000, 140000, 160000, 180000, 200000),
}
# PDF section 2: Level -> (category, min, max); L10 "1,20,000 onwards"
SECTION_2 = {
	"L1": ("Trainee / Support Staff", 16000, 18000),
	"L2": ("Operator / Skilled Technician", 18000, 22000),
	"L3": ("Junior Executive / Junior Engineer", 20000, 28000),
	"L4": ("Executive / Engineer", 25000, 35000),
	"L5": ("Senior Engineer / Senior Executive / Supervisor", 30000, 45000),
	"L6": ("Assistant Manager / Section Manager", 40000, 60000),
	"L7": ("Manager / Department Manager", 50000, 75000),
	"L8": ("Senior Manager / Functional Head", 60000, 80000),
	"L9": ("General Manager / Business Head", 75000, 120000),
	"L10": ("Director / Top Management", 120000, 0),
}


class TestEmployeeGradesImport(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		eg.execute()

	def setUp(self):
		frappe.db.savepoint("grades_import_test")
		self.addCleanup(frappe.db.rollback, save_point="grades_import_test")

	def test_file_matches_the_pdf(self):
		grades = {g.name: g for g in loader.read_grades()}
		self.assertEqual(sorted(grades), sorted(f"L{n}-B{n}" for n in range(1, 11)))
		for level, amounts in SECTION_3.items():
			grade = grades[f"{level}-B{level[1:]}"]
			with self.subTest(level=level):
				self.assertEqual((grade[eg.LEVEL], grade[eg.BAND]), (level, f"B{level[1:]}"))
				self.assertEqual(
					[(r["sub_band"], r["gross_amount"]) for r in grade[eg.SUB_BANDS]],
					list(zip("ABCDE", amounts)),
				)
				category, low, high = SECTION_2[level]
				self.assertEqual(
					(grade[eg.CATEGORY], grade[eg.MIN_GROSS], grade.get(eg.MAX_GROSS) or 0), (category, low, high)
				)
				self.assertEqual(grade.default_base_pay, amounts[0])

	def test_loaded_on_the_site(self):
		loader.load_grades()
		l5 = frappe.get_doc("Employee Grade", "L5-B5")
		self.assertEqual([r.gross_amount for r in l5.get(eg.SUB_BANDS)], list(SECTION_3["L5"]))

	def test_create_only(self):
		loader.load_grades()
		l5 = frappe.get_doc("Employee Grade", "L5-B5")
		l5.get(eg.SUB_BANDS)[0].gross_amount = 31000
		l5.save()
		frappe.delete_doc("Employee Grade", "L9-B9", force=True)

		self.assertEqual(loader.load_grades(), ["L9-B9"])
		self.assertEqual(frappe.get_doc("Employee Grade", "L5-B5").get(eg.SUB_BANDS)[0].gross_amount, 31000)
		self.assertEqual(len(frappe.get_doc("Employee Grade", "L9-B9").get(eg.SUB_BANDS)), 5)

	def test_default_salary_structure(self):
		frappe.delete_doc("Employee Grade", "L9-B9", force=True, ignore_missing=True)
		frappe.delete_doc("Employee Grade", "L8-B8", force=True, ignore_missing=True)
		with patch.object(loader, "default_structure", return_value=None):
			loader.load_grades()
		self.assertFalse(frappe.db.get_value("Employee Grade", "L9-B9", "default_salary_structure"))

		structure = frappe.db.get_value("Salary Structure", {"docstatus": 1}, "name")
		frappe.delete_doc("Employee Grade", "L9-B9", force=True)
		with patch.object(loader, "default_structure", return_value=structure):
			loader.load_grades()
		self.assertEqual(frappe.db.get_value("Employee Grade", "L9-B9", "default_salary_structure"), structure)

	def test_min_above_max_refused(self):
		loader.load_grades()
		doc = frappe.get_doc("Employee Grade", "L3-B3")
		doc.set(eg.MIN_GROSS, 30000)
		with self.assertRaises(eg.InvalidGrossRangeError):
			doc.save()

	def test_sub_band_outside_range_warns(self):
		loader.load_grades()
		doc = frappe.get_doc("Employee Grade", "L3-B3")
		doc.get(eg.SUB_BANDS)[4].gross_amount = 29000
		frappe.clear_messages()
		doc.save()
		self.assertIn("Sub Band E", " ".join(str(m) for m in frappe.get_message_log()))
		self.assertEqual(frappe.db.get_value("Employee Grade Sub Band", doc.get(eg.SUB_BANDS)[4].name, "gross_amount"), 29000)

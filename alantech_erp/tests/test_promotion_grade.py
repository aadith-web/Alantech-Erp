# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Promotion Grade / Sub Band / Amount (setup/promotion_grade.py, ClickUp 14yr2e58nc6).

Run:
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_promotion_grade

Unit: the custom fields (alt_ prefix, so they export with the fixtures). Integration, with a grade
of the site that has sub bands and an active employee (skipped otherwise): Amount filled from the
Gross Amount and editable; Sub Band must be an enabled sub band of the Grade; Sub Band needs a Grade;
Amount above zero; Amount becomes the Revised CTC (and the Employee's CTC) on submit; promotions
without a Grade unchanged.
Data: each test runs in a savepoint that is rolled back.
"""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import flt, today

from alantech_erp.setup.promotion_grade import AMOUNT, GRADE, SUB_BAND, PromotionGradeError


class UnitTestPromotionGradeFields(UnitTestCase):
	def test_fields(self):
		meta = frappe.get_meta("Employee Promotion")
		self.assertEqual(meta.get_field(GRADE).options, "Employee Grade")
		self.assertEqual(meta.get_field(SUB_BAND).options, "Sub Band")
		amount = meta.get_field(AMOUNT)
		self.assertEqual((amount.fieldtype, amount.read_only), ("Currency", 0))
		for f in (GRADE, SUB_BAND, AMOUNT):
			self.assertTrue(f.startswith("alt_"))


class IntegrationTestPromotionGrade(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		rows = frappe.get_all("Employee Grade Sub Band", filters={"parenttype": "Employee Grade", "parentfield": "alt_sub_bands"},
			fields=["parent", "sub_band", "gross_amount"], order_by="parent, idx", limit=50)
		by_grade = {}
		for r in rows:
			by_grade.setdefault(r.parent, []).append(r)
		cls.grade, cls.bands = next(((g, b) for g, b in by_grade.items() if len(b) >= 1), (None, None))
		employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name", order_by="creation", limit=1)
		if not cls.grade or not employees:
			raise cls.skipTest(cls, "Need an Employee Grade with sub bands and an active employee")
		cls.employee = employees[0]
		cls.other_band = next((s for s in frappe.get_all("Sub Band", pluck="name") if s not in {b.sub_band for b in cls.bands}), None)

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("promo_grade")
		self.addCleanup(frappe.db.rollback, save_point="promo_grade")

	def promotion(self, **values):
		return frappe.get_doc({"doctype": "Employee Promotion", "employee": self.employee, "promotion_date": today(),
			**values})

	def test_amount_filled_and_editable(self):
		band = self.bands[0]
		doc = self.promotion(**{GRADE: self.grade, SUB_BAND: band.sub_band}).insert()
		self.assertEqual(flt(doc.get(AMOUNT)), flt(band.gross_amount))
		doc.set(AMOUNT, flt(band.gross_amount) + 1500)
		doc.save()
		self.assertEqual(flt(doc.get(AMOUNT)), flt(band.gross_amount) + 1500)

	def test_sub_band_must_be_on_grade(self):
		other = self.other_band or frappe.get_doc({"doctype": "Sub Band", "sub_band": "_T Z", "enabled": 1}).insert().name
		with self.assertRaises(PromotionGradeError) as raised:
			self.promotion(**{GRADE: self.grade, SUB_BAND: other}).insert()
		self.assertIn("is not an enabled sub band of Grade", str(raised.exception))

	def test_disabled_sub_band_refused(self):
		band = self.bands[0].sub_band
		frappe.db.set_value("Sub Band", band, "enabled", 0)
		with self.assertRaises(PromotionGradeError):
			self.promotion(**{GRADE: self.grade, SUB_BAND: band}).insert()

	def test_sub_band_needs_grade_and_amount_above_zero(self):
		with self.assertRaises(PromotionGradeError):
			self.promotion(**{SUB_BAND: self.bands[0].sub_band}).insert()
		with self.assertRaises(PromotionGradeError):
			self.promotion(**{GRADE: self.grade, SUB_BAND: self.bands[0].sub_band, AMOUNT: -5}).insert()

	def test_amount_becomes_revised_ctc_on_submit(self):
		doc = self.promotion(**{GRADE: self.grade, SUB_BAND: self.bands[0].sub_band})
		doc.insert()
		doc.set(AMOUNT, 77777)
		doc.save()
		doc.submit()
		self.assertEqual(flt(doc.revised_ctc), 77777)
		self.assertEqual(flt(frappe.db.get_value("Employee", self.employee, "ctc")), 77777)

	def test_promotion_without_grade_unchanged(self):
		doc = self.promotion().insert()
		self.assertFalse(doc.get(AMOUNT))
		doc.submit()
		self.assertFalse(flt(doc.revised_ctc))

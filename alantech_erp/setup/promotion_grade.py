# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Employee Promotion: Grade, Sub Band and an editable Amount (ClickUp 14yr2e58nc6, parent
14yr2e58m5b "salary revision through Grade / Sub Band").

Fields (custom, alt_ prefix, exported with the fixtures), in the Salary Details section:
- Grade (alt_grade, Link Employee Grade).
- Sub Band (alt_sub_band, Link Sub Band): only the enabled sub bands on the chosen Grade
  (Employee Grade > Sub Bands, setup/employee_grade.py).
- Amount (alt_amount, Currency): filled with the Gross Amount of that Grade + Sub Band, editable.

Rules (Employee Promotion validate, so the form, Data Import and the API obey them):
- A Sub Band needs a Grade, must be on that Grade and enabled.
- Grade + Sub Band without an Amount: the Gross Amount is filled in.
- With a Grade or Sub Band, the Amount must be above zero (and never negative).
- On submit (before_submit, before HRMS writes the CTC to the Employee) the Amount becomes the
  Revised CTC.
Promotions without a Grade are not affected.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

GRADE, SUB_BAND, AMOUNT = "alt_grade", "alt_sub_band", "alt_amount"

CUSTOM_FIELDS = {
	"Employee Promotion": [
		{
			"fieldname": GRADE,
			"label": "Grade",
			"fieldtype": "Link",
			"options": "Employee Grade",
			"insert_after": "salary_details_section",
		},
		{
			"fieldname": SUB_BAND,
			"label": "Sub Band",
			"fieldtype": "Link",
			"options": "Sub Band",
			"insert_after": GRADE,
			"depends_on": GRADE,
			"mandatory_depends_on": GRADE,
			"description": "Sub bands of the chosen Grade.",
		},
		{
			"fieldname": AMOUNT,
			"label": "Amount",
			"fieldtype": "Currency",
			"options": "salary_currency",
			"insert_after": SUB_BAND,
			"depends_on": GRADE,
			"mandatory_depends_on": GRADE,
			"description": "Gross Amount of the Grade and Sub Band; change it if needed. Becomes the Revised CTC on submit.",
		},
	]
}


class PromotionGradeError(frappe.ValidationError):
	pass


def fail(message):
	frappe.throw(message, PromotionGradeError, title=_("Grade and Sub Band"))


def execute():
	create_custom_fields(CUSTOM_FIELDS, update=True)


def sub_band_gross(grade, sub_band):
	"""Gross Amount of an enabled `sub_band` on `grade`, or None when it is not there / disabled."""
	from alantech_erp.setup.employee_grade import SUB_BANDS

	if not frappe.db.get_value("Sub Band", sub_band, "enabled"):
		return None
	return frappe.db.get_value(
		"Employee Grade Sub Band",
		{"parenttype": "Employee Grade", "parent": grade, "parentfield": SUB_BANDS, "sub_band": sub_band},
		"gross_amount",
	)


def validate(doc, method=None):
	grade, sub_band = doc.get(GRADE), doc.get(SUB_BAND)
	if flt(doc.get(AMOUNT)) < 0:
		fail(_("Amount cannot be negative."))
	if not grade and not sub_band:
		return
	if sub_band and not grade:
		fail(_("Select the Grade before the Sub Band."))
	if not sub_band:
		fail(_("Select a Sub Band of Grade {0}.").format(grade))
	gross = sub_band_gross(grade, sub_band)
	if gross is None:
		fail(_("Sub Band {0} is not an enabled sub band of Grade {1}.").format(sub_band, grade))
	if not flt(doc.get(AMOUNT)):
		doc.set(AMOUNT, gross)
	if flt(doc.get(AMOUNT)) <= 0:
		fail(_("Amount must be above zero."))


def before_submit(doc, method=None):
	if doc.get(GRADE) and flt(doc.get(AMOUNT)) > 0:
		doc.revised_ctc = flt(doc.get(AMOUNT))

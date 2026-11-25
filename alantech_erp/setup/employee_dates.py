"""Employee: Offer Date, Date of Joining, Probation Period and Confirmation Date checked against each other.

ERPNext only compares Date of Joining with Date of Birth / Retirement / Relieving / Contract End.
Rules (Employee.validate, hooks.py; the form applies the same at once, public/js/employee.js):

- Offer Date (scheduled_confirmation_date) on or before Date of Joining.
- Confirmation Date (final_confirmation_date) after Date of Joining.
- Probation Period (Months) (alt_probation_period, setup/employee_payroll_fields.py) set:
  Confirmation Date = Date of Joining + that many months.
  - blank Confirmation Date: filled;
  - Date of Joining or Probation Period changed: Confirmation Date follows;
  - a different Confirmation Date entered with a Probation Period (form, import, API): refused,
    with the expected date (clear the Probation Period to enter another date).

Checked on a new employee and whenever one of the four fields changes, so an unrelated edit of an
older employee with inconsistent dates is not blocked (those are listed by `inconsistent_employees`).
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, formatdate, getdate

JOINING = "date_of_joining"
OFFER = "scheduled_confirmation_date"
CONFIRMATION = "final_confirmation_date"
PROBATION = "alt_probation_period"
FIELDS = (JOINING, OFFER, CONFIRMATION, PROBATION)


class EmployeeDateError(frappe.ValidationError):
	pass


def fail(message):
	frappe.throw(message, EmployeeDateError, title=_("Check the Employment Dates"))


def expected_confirmation(joining, months):
	return getdate(add_months(getdate(joining), cint(months))) if joining and cint(months) > 0 else None


def validate_employment_dates(doc, method=None):
	before = None if doc.is_new() else doc.get_doc_before_save()
	changed = lambda field: before is None or _value(field, before.get(field)) != _value(field, doc.get(field))  # noqa: E731
	if before is not None and not any(changed(f) for f in FIELDS):
		return

	joining = getdate(doc.get(JOINING)) if doc.get(JOINING) else None
	offer = getdate(doc.get(OFFER)) if doc.get(OFFER) else None
	if joining and offer and offer > joining:
		fail(_("Offer Date ({0}) cannot be after the Date of Joining ({1}).").format(
			formatdate(offer), formatdate(joining)))

	expected = expected_confirmation(joining, doc.get(PROBATION))
	if expected:
		current = getdate(doc.get(CONFIRMATION)) if doc.get(CONFIRMATION) else None
		if not current or (not changed(CONFIRMATION) and (changed(JOINING) or changed(PROBATION))):
			doc.set(CONFIRMATION, expected)
		elif current != expected:
			fail(_("Confirmation Date must be {0}: Date of Joining ({1}) + Probation Period of {2} month(s). "
				"Clear the Probation Period to enter another Confirmation Date.").format(
				formatdate(expected), formatdate(joining), cint(doc.get(PROBATION))))

	confirmation = getdate(doc.get(CONFIRMATION)) if doc.get(CONFIRMATION) else None
	if joining and confirmation and confirmation <= joining:
		fail(_("Confirmation Date ({0}) must be after the Date of Joining ({1}).").format(
			formatdate(confirmation), formatdate(joining)))


def _value(field, v):
	if field == PROBATION:
		return cint(v)
	return getdate(v) if v else None


def inconsistent_employees():
	"""Existing employees whose dates break the rules (for HR to correct)."""
	out = []
	for e in frappe.get_all("Employee", fields=["name", "employee_name", *FIELDS]):
		problems = []
		if e[JOINING] and e[OFFER] and getdate(e[OFFER]) > getdate(e[JOINING]):
			problems.append("Offer Date after Date of Joining")
		if e[JOINING] and e[CONFIRMATION] and getdate(e[CONFIRMATION]) <= getdate(e[JOINING]):
			problems.append("Confirmation Date not after Date of Joining")
		expected = expected_confirmation(e[JOINING], e[PROBATION])
		if expected and e[CONFIRMATION] and getdate(e[CONFIRMATION]) != expected:
			problems.append(f"Confirmation Date is not Date of Joining + {cint(e[PROBATION])} month(s) ({expected})")
		if problems:
			out.append({"name": e.name, "employee_name": e.employee_name, "problems": problems})
	return out

# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Loan Rule — Employee Loan Rules, LR-01 (ClickUp https://app.clickup.com/t/14yr2e57ghc,
parent 14yr2e57ghb).

One rule per loan policy, named by rule_name. A Frappe Lending Loan Application with
Applicant Type = Employee is checked against the single matching rule (engine: LR-04,
hooks: LR-05).

Rules enforced here (on save):
- valid_from <= valid_upto (either may be blank)
- max_age >= min_age when both are set
- limits and ages are never negative; 0 / blank means "no limit"
- no duplicate rows in an applicability table; a blank table means "applies to all"
- override_role is required when allow_override is ticked, and cleared when it is not

Priority: the higher number wins; ties are broken by specificity (get_specificity), then name.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate

# (table fieldname, link fieldname in the child row)
APPLICABILITY_TABLES = (
	("loan_products", "loan_product"),
	("employment_types", "employment_type"),
	("grades", "grade"),
	("designations", "designation"),
	("departments", "department"),
	("branches", "branch"),
)

NON_NEGATIVE_FIELDS = (
	"min_service_months",
	"min_age",
	"max_age",
	"max_active_loans",
	"max_open_applications",
	"cooling_off_months",
	"max_loans_per_year",
)


class LoanRule(Document):
	def validate(self):
		self.rule_name = (self.rule_name or "").strip()
		self.validate_dates()
		self.validate_non_negative()
		self.validate_age_range()
		self.validate_applicability()
		self.validate_override()

	def validate_dates(self):
		if self.valid_from and self.valid_upto and getdate(self.valid_from) > getdate(self.valid_upto):
			frappe.throw(_("Valid From cannot be after Valid Upto."))

	def validate_non_negative(self):
		for field in NON_NEGATIVE_FIELDS:
			if cint(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(field))))

	def validate_age_range(self):
		if cint(self.min_age) and cint(self.max_age) and cint(self.max_age) < cint(self.min_age):
			frappe.throw(_("Maximum Age cannot be less than Minimum Age."))

	def validate_applicability(self):
		for table, field in APPLICABILITY_TABLES:
			values = [row.get(field) for row in self.get(table)]
			if len(values) != len(set(values)):
				frappe.throw(_("Duplicate entries in {0}.").format(_(self.meta.get_label(table))))

	def validate_override(self):
		if not self.allow_override:
			self.override_role = None
		elif not self.override_role:
			frappe.throw(_("Override Role is required when Allow Override is ticked."))

	def get_applicability(self):
		"""Return {table fieldname: set of values}; an empty set means the rule applies to all."""
		return {
			table: {row.get(field) for row in self.get(table) if row.get(field)}
			for table, field in APPLICABILITY_TABLES
		}

	def get_specificity(self):
		"""Number of filled applicability tables; the more specific rule wins a priority tie."""
		return sum(1 for values in self.get_applicability().values() if values)

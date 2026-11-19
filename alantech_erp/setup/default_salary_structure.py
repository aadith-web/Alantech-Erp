"""Default Salary Structure with the earnings of the Alantech payslip, percentages editable by HR.

ClickUp: https://app.clickup.com/t/14yr2e586v4 (parent 14yr2e586v0, "Employee Grade, Sub Band &
Salary Structure creation from Employee form")

Earnings (Gross = base of the Salary Structure Assignment):

    Basic                 40   % of Gross      38,500 -> 15,400
    Dearness Allowance    25   % of Basic                 3,850
    House Rent Allowance  40   % of Basic                 6,160
    Transport Allowance   12.5 % of Basic                 1,925
    Medical Allowance     10   % of Basic                 1,540
    Special Allowance     12.5 % of Basic                 1,925
    Fixed Variable        50   % of Basic                 7,700
                                               total     38,500

Editable percentages: each earning row of a Salary Structure has Percentage and Percentage Of
(a component of the structure, blank = Gross), editable also after submit. The row's formula is
written from them on every save (Salary Structure validate / before_update_after_submit), so HR
changes a number instead of a formula; a row without a Percentage keeps its own formula.
Formulas are written from `base` (DA = base * 40 / 100 * 25 / 100), not from the Basic
component: Basic is prorated by payment days, and a formula using it on a row that is also
prorated would be cut twice (HRMS refuses that structure).

Basic and House Rent Allowance are the existing components: the overtime rate is worked out from
them (setup/shifts.py OVERTIME_APPLICABLE_COMPONENTS). Deductions (PF, ESI, PT) are not added
until their rules are confirmed (open point on the parent task).

Hooked in hooks.py: doc_events Salary Structure (validate, before_update_after_submit), and
`execute` (create-only: components, the structure per company) from the patch
patches/v16/default_salary_structure.py, which also makes it the default of every Employee Grade.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import flt

STRUCTURE_NAME = "Default Salary Structure"
PERCENT, PERCENT_OF = "alt_percentage", "alt_percentage_of"
GROSS = "base"  # the Salary Structure Assignment's Base, i.e. the gross from the grade's sub band

# (component, abbr, percentage, of component or None for Gross); existing components keep their abbr
EARNINGS = (
	("Basic", "B", 40, None),
	("Dearness Allowance", "DA", 25, "Basic"),
	("House Rent Allowance", "HRA", 40, "Basic"),
	("Transport Allowance", "TA", 12.5, "Basic"),
	("Medical Allowance", "MA", 10, "Basic"),
	("Special Allowance", "SA", 12.5, "Basic"),
	("Fixed Variable", "FV", 50, "Basic"),
)

ON_STRUCTURE = "eval:doc.parenttype=='Salary Structure'"
CUSTOM_FIELDS = {
	"Salary Detail": [
		{
			"fieldname": PERCENT,
			"fieldtype": "Percent",
			"label": "Percentage",
			"insert_after": "amount_based_on_formula",
			"allow_on_submit": 1,
			"in_list_view": 0,
			"depends_on": ON_STRUCTURE,
			"description": "The formula is written from this percentage on save. Clear it to write your own formula.",
		},
		{
			"fieldname": PERCENT_OF,
			"fieldtype": "Link",
			"options": "Salary Component",
			"label": "Percentage Of",
			"insert_after": PERCENT,
			"allow_on_submit": 1,
			"depends_on": f"eval:doc.parenttype=='Salary Structure' && doc.{PERCENT}",
			"description": "A component of this structure, e.g. Basic. Blank: Gross (Base of the Salary Structure Assignment).",
		},
	]
}


class PercentageFormulaError(frappe.ValidationError):
	pass


# ---------------------------------------------------------------------- formulas
def percentage_formulas(rows):
	"""[(row, formula)] for the rows with a Percentage. A row "of" another component multiplies that
	component's own expression, down to `base`: DA 25% of Basic 40% of Gross ->
	"base * 40 / 100 * 25 / 100". Raises PercentageFormulaError for a component that is not in
	the rows, has no Percentage itself, or refers back to itself."""
	by_component = {row.salary_component: row for row in rows}

	def expression(row, seen):
		if row.salary_component in seen:
			frappe.throw(
				_("Row {0}: {1} is worked out from itself through Percentage Of ({2}).").format(
					row.idx, frappe.bold(row.salary_component), " > ".join(seen + [row.salary_component])
				),
				PercentageFormulaError,
				title=_("Invalid Percentage"),
			)
		of = row.get(PERCENT_OF)
		if not of:
			start = GROSS
		else:
			parent = by_component.get(of)
			if not parent:
				frappe.throw(
					_("Row {0}: {1} is a percentage of {2}, which is not in this salary structure.").format(
						row.idx, frappe.bold(row.salary_component), frappe.bold(of)
					),
					PercentageFormulaError,
					title=_("Invalid Percentage"),
				)
			if parent.get(PERCENT) in (None, ""):
				frappe.throw(
					_(
						"Row {0}: {1} is a percentage of {2}, which has no Percentage. Give {2} a "
						"Percentage, or write the formula of {1} yourself."
					).format(row.idx, frappe.bold(row.salary_component), frappe.bold(of)),
					PercentageFormulaError,
					title=_("Invalid Percentage"),
				)
			start = expression(parent, seen + [row.salary_component])
		return f"{start} * {number(row.get(PERCENT))} / 100"

	return [(row, expression(row, [])) for row in rows if row.get(PERCENT) not in (None, "")]


def number(value):
	"""12.5 -> "12.5", 40.0 -> "40"."""
	value = flt(value)
	return str(int(value)) if value == int(value) else repr(value)


def set_percentage_formulas(doc, method=None):
	"""Salary Structure validate / before_update_after_submit: rows with a Percentage get their
	formula written from it. HRMS keeps the formula it read before saving in `_formula` and puts it
	back after the save, so both are set."""
	rows = list(doc.get("earnings") or []) + list(doc.get("deductions") or [])
	for row, formula in percentage_formulas(rows):
		if flt(row.get(PERCENT)) < 0:
			frappe.throw(
				_("Row {0}: the Percentage of {1} cannot be negative.").format(row.idx, frappe.bold(row.salary_component)),
				PercentageFormulaError,
				title=_("Invalid Percentage"),
			)
		row.amount_based_on_formula = 1
		row.amount = 0
		row.formula = formula
		row._formula = formula


# ---------------------------------------------------------------------- setup
def execute():
	"""Create-only: the Percentage fields, the earning components and the structure of each company."""
	create_custom_fields(CUSTOM_FIELDS, update=True)
	ensure_components()
	return [ensure_structure(company) for company in frappe.get_all("Company", pluck="name")]


def ensure_components():
	for component, abbr, _percent, _of in EARNINGS:
		if frappe.db.exists("Salary Component", component):
			continue
		frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": component,
				"salary_component_abbr": abbr,
				"type": "Earning",
				"depends_on_payment_days": 1,
			}
		).insert(ignore_permissions=True)


def structure_name(company):
	"""Default Salary Structure; with several companies, one per company: "... - <abbr>"."""
	if frappe.db.count("Company") == 1:
		return STRUCTURE_NAME
	return f"{STRUCTURE_NAME} - {frappe.get_cached_value('Company', company, 'abbr')}"


def ensure_structure(company):
	"""The company's default structure, submitted; an existing one is left as HR has it."""
	name = structure_name(company)
	if frappe.db.exists("Salary Structure", name):
		return name
	structure = frappe.get_doc(
		{
			"doctype": "Salary Structure",
			"__newname": name,
			"company": company,
			"is_active": "Yes",
			"payroll_frequency": "Monthly",
			"currency": frappe.get_cached_value("Company", company, "default_currency"),
			"earnings": [
				{
					"salary_component": component,
					"abbr": frappe.db.get_value("Salary Component", component, "salary_component_abbr") or abbr,
					PERCENT: percent,
					PERCENT_OF: of,
				}
				for component, abbr, percent, of in EARNINGS
			],
		}
	)
	structure.insert(ignore_permissions=True)
	structure.submit()
	return name


def set_default_for_grades(structure):
	"""Every Employee Grade gets `structure` as Default Salary Structure; returns the grades changed."""
	changed = []
	for grade in frappe.get_all("Employee Grade", fields=["name", "default_salary_structure"]):
		if grade.default_salary_structure != structure:
			frappe.db.set_value("Employee Grade", grade.name, "default_salary_structure", structure)
			changed.append(grade.name)
	return changed

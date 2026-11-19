"""Default Salary Structure with the payslip earnings, default of every Employee Grade.

ClickUp: https://app.clickup.com/t/14yr2e586v4. The structure and components are made by
setup/default_salary_structure.py (create-only). With one company, its structure becomes the
Default Salary Structure of all grades (they had General Shift Salary Structure, set by
patches/v16/employee_grades_from_pdf.py as the only structure then). Runs once: a default HR
changes later is kept.
"""

from alantech_erp.setup import default_salary_structure


def execute():
	structures = default_salary_structure.execute()
	if len(structures) == 1:
		default_salary_structure.set_default_for_grades(structures[0])

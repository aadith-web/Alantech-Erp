"""Employee Grades L1-B1 to L10-B10 with Sub Bands A to E (ClickUp 14yr2e586v3).

Source: PDF "Employee Grade, Level & Salary Band Structure" Ver1, sections 2 and 3, kept as the
Data Import file setup/data/employee_grades.csv. HR can load the same file with Data Import >
Employee Grade > Insert New Records.

The file is read with Frappe's Data Import parser, so the patch and Data Import read it the same
way. Create-only: a grade that already exists is left as HR has it. Default Salary Structure is
set when the company has exactly one active submitted salary structure; the default structure of
ClickUp 14yr2e586v4 replaces it there.
"""

import os

import frappe

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "setup", "data", "employee_grades.csv")


def execute():
	from alantech_erp.setup import employee_grade

	frappe.reload_doc("alantech", "doctype", "sub_band")
	frappe.reload_doc("alantech", "doctype", "employee_grade_sub_band")
	employee_grade.execute()  # custom fields and Sub Bands A to E before the grades
	return load_grades()


def read_grades(path=CSV_PATH):
	"""The grades in the file, as Data Import parses them: list of dicts with the Sub Bands rows."""
	from frappe.core.doctype.data_import.importer import Importer

	# an unsaved Data Import: this Frappe version reads its options even without one
	data_import = frappe.get_doc(
		{"doctype": "Data Import", "reference_doctype": "Employee Grade", "import_type": "Insert New Records"}
	)
	importer = Importer(
		"Employee Grade", data_import=data_import, file_path=os.path.abspath(path), import_type="Insert New Records",
		console=True,  # read the file from disk, not from a File record
	)
	return [payload.doc for payload in importer.import_file.get_payloads_for_import()]


def default_structure():
	structures = frappe.get_all(
		"Salary Structure", filters={"docstatus": 1, "is_active": "Yes"}, pluck="name", limit=2
	)
	return structures[0] if len(structures) == 1 else None


def load_grades(path=CSV_PATH):
	"""Insert the grades that do not exist yet; return their names."""
	structure = default_structure()
	created = []
	for data in read_grades(path):
		if frappe.db.exists("Employee Grade", data.name):
			continue
		doc = frappe.new_doc("Employee Grade")
		doc.update(data)
		if structure and not doc.default_salary_structure:
			doc.default_salary_structure = structure
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	return created

# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Fill the empty Applicant Name on existing employee Loans and Loan Applications from the Employee
(new ones are filled on save: loan_rules/loan.py set_applicant_name)."""

import frappe


def execute():
	for doctype in ("Loan", "Loan Application"):
		if not frappe.db.table_exists(doctype):
			continue  # Lending not installed
		frappe.db.sql(
			f"""
			update `tab{doctype}` d
			join `tabEmployee` e on e.name = d.applicant
			set d.applicant_name = e.employee_name
			where d.applicant_type = 'Employee' and ifnull(d.applicant_name, '') = ''
			"""
		)

"""Employee Notice Period for every existing employee (ClickUp 14yr2e57r71).

New employees get theirs on save (employee_notice_period.employee_on_update). Employees made before
get one here: their Notice (days) when set, else the default (HR Settings, 30).
"""

import frappe

from alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period import (
	DOCTYPE,
	create_notice_period,
)
from alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period import (
	execute as create_fields,
)


def execute():
	frappe.reload_doc("alantech", "doctype", "employee_notice_period")
	create_fields()  # HR Settings > Default Notice Period (Days), read below
	have = set(frappe.get_all(DOCTYPE, pluck="employee"))
	for employee in frappe.get_all(
		"Employee", fields=["name", "notice_number_of_days", "date_of_joining"], order_by="creation asc"
	):
		if employee.name not in have:
			create_notice_period(employee)

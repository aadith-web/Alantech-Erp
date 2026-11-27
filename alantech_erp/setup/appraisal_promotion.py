# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Appraisal -> Employee Promotion: "Create Promotion" on a submitted Appraisal (ClickUp 14yr2e58nc7,
parent 14yr2e58m5c).

- The button (public/js/appraisal.js) shows only on a submitted Appraisal (not Draft or Cancelled)
  and only for users who may create an Employee Promotion (HR User / HR Manager).
- It opens a NEW, unsaved Employee Promotion with the employee, company and department of the
  appraisal. Nothing is created automatically: HR reviews it, fills the Promotion Date and the
  changes (Grade, Sub Band, Amount ...) and saves / submits it as usual.
- make_promotion refuses a Draft or Cancelled appraisal, so the rule also holds outside the form.
"""

import frappe
from frappe import _


@frappe.whitelist()
def make_promotion(source_name, target_doc=None):
	appraisal = frappe.get_doc("Appraisal", source_name)
	appraisal.check_permission("read")
	if appraisal.docstatus != 1:
		frappe.throw(_("Submit the Appraisal before creating a promotion from it."), title=_("Appraisal Not Submitted"))
	if not frappe.has_permission("Employee Promotion", "create"):
		frappe.throw(_("You are not allowed to create an Employee Promotion."), frappe.PermissionError)

	promotion = frappe.new_doc("Employee Promotion")
	promotion.update({
		"employee": appraisal.employee,
		"employee_name": appraisal.employee_name,
		"company": appraisal.company,
		"department": appraisal.department or frappe.db.get_value("Employee", appraisal.employee, "department"),
	})
	return promotion

# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR Manager creates Loans (LR-09 follow-up).

ClickUp: https://app.clickup.com/t/14yr2e57ghn
setup/loan_permissions.py first gave HR Manager read-only rights on Loan; the business wants HR
Managers to create the Loan from an Approved Loan Application. The setup is create-only, so the
existing HR Manager row on Loan is upgraded here once: rights are only added, never removed.
"""

import frappe

from alantech_erp.setup.loan_permissions import PERMISSIONS


def execute():
	key = {"parent": "Loan", "role": "HR Manager", "permlevel": 0, "if_owner": 0}
	if not frappe.db.exists("Custom DocPerm", key):
		return  # setup/loan_permissions.execute (after_migrate) creates it with full rights
	rights = PERMISSIONS[("Loan", "HR Manager", 0)]
	frappe.db.set_value("Custom DocPerm", key, {right: 1 for right in rights})
	frappe.clear_cache(doctype="Loan")

# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Loan Management flow (HR-F05-x): every HR Manager is also a Loan Manager.

ClickUp: https://app.clickup.com/t/14yr2e57kyk (parent HR-F05 14yr2e56cah)

The HR Manager runs the whole Lending flow: approve the Loan Application, create and sanction the
Loan, Loan Disbursement, Loan Repayment (prepayment / foreclosure), interest accrual, Loan Write
Off / Refund / Restructure. Lending gives those doctypes to its Loan Manager role and also checks
that role by name (e.g. Loan Installment Skip Request approval), so the role itself is assigned,
as the flow spec says; per-doctype rights would not cover the name checks.

    user_validate(doc)  User doc_event validate: a user with HR Manager gets Loan Manager added
                        (also when a role profile set the roles; runs after the profile is applied)
    execute()           after_migrate: existing HR Managers without Loan Manager get it
    setup/access.EXTRA_PROFILE_ROLES  the HR role profiles list Loan Manager too, so a profile
                        save keeps it

Removing HR Manager from a user does not remove Loan Manager (it may have been given on its own);
remove it by hand when needed.
"""

import frappe

# role held -> role added
COUPLED_ROLES = {"HR Manager": "Loan Manager"}


def missing_roles(roles):
	roles = set(roles)
	return [added for held, added in COUPLED_ROLES.items() if held in roles and added not in roles]


def user_validate(doc, method=None):
	if doc.name in ("Administrator", "Guest") or not frappe.db.exists("Role", "Loan Manager"):
		return
	for role in missing_roles(r.role for r in doc.get("roles", [])):
		doc.append("roles", {"role": role})


def execute():
	if not frappe.db.exists("Role", "Loan Manager"):
		return  # Lending not installed
	for held in COUPLED_ROLES:
		users = frappe.get_all(
			"Has Role", filters={"role": held, "parenttype": "User"}, pluck="parent", distinct=True
		)
		for user in users:
			if user in ("Administrator", "Guest") or not missing_roles(frappe.get_roles(user)):
				continue
			doc = frappe.get_doc("User", user)
			doc.flags.ignore_permissions = True
			doc.save()  # user_validate adds the role

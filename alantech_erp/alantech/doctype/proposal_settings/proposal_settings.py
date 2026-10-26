# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt

"""Proposal Settings: company-wide defaults for Technical Offers (letter head, signatory, standard texts, terms)."""

import frappe
from frappe.model.document import Document


class ProposalSettings(Document):
	pass


@frappe.whitelist()
def load_standard_library():
	frappe.only_for(("System Manager", "Sales Manager"))
	from alantech_erp.setup.proposal_library import load

	return load()

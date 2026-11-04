# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""CRM-F07 Quotation Approval: approve with remarks, owner edits until Send to Client.

Run:
    bench --site <site> run-tests --module alantech_erp.tests.test_quotation_approval

Uses test-qa-* users and a "TEST-QA" customer; everything is rolled back after each test.
"""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, nowdate

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.sales import APPROVED, LEVEL_2_LIMIT_FIELD, PENDING_LEVEL_2, REJECTED, SENT_TO_CLIENT
from alantech_erp.sales.quotation import set_approval_remarks, set_rejection_remarks


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	return email


def _first(doctype, filters=None):
	return frappe.db.get_value(doctype, filters or {}, "name")


class TestQuotationApproval(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from alantech_erp.sales import workflow_is_active

		if not workflow_is_active():
			raise Exception("Run bench migrate first: workflow ALT Quotation Approval is not active")
		frappe.set_user("Administrator")
		cls.owner = _user("test-qa-owner@example.com", ["Sales User"])
		cls.other = _user("test-qa-other@example.com", ["Sales User"])
		cls.manager = _user("test-qa-manager@example.com", ["Sales User", "Sales Manager"])
		cls.director = _user(
			"test-qa-director@example.com", ["Sales User", "Sales Manager", "Quotation Level 2 Approver"]
		)
		cls.company = _first("Company")
		cls.currency = frappe.get_cached_value("Company", cls.company, "default_currency")
		hsn = _first("GST HSN Code") if frappe.db.exists("DocType", "GST HSN Code") else None
		if hsn is None and frappe.db.exists("DocType", "GST HSN Code"):
			hsn = frappe.get_doc({"doctype": "GST HSN Code", "hsn_code": "998311"}).insert().name
		if not frappe.db.exists("Item", "TEST-QA-ITEM"):
			item = {
				"doctype": "Item",
				"item_code": "TEST-QA-ITEM",
				"item_group": _first("Item Group", {"is_group": 0}),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
			if hsn:
				item["gst_hsn_code"] = hsn
			frappe.get_doc(item).insert()
		cls.customer = frappe.db.get_value("Customer", {"customer_name": "TEST-QA Customer LLC"})
		if not cls.customer:
			cls.customer = (
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": "TEST-QA Customer LLC",
						"customer_type": "Company",
						"customer_group": _first("Customer Group", {"is_group": 0}),
						"territory": _first("Territory", {"is_group": 0}) or _first("Territory"),
						"industry": _first("Industry Type")
						or frappe.get_doc({"doctype": "Industry Type", "industry": "TEST-QA"}).insert().name,
						"alt_tax_type": "Overseas",
						"default_currency": cls.currency,
						"mobile_no": "+971-501119901",
						"email_id": "qa@test-qa.example",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		# Level 1 only unless a test sets a limit
		frappe.db.set_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD, 0)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD, 0)

	def _quotation(self, rate=100):
		frappe.set_user(self.owner)
		doc = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": self.customer,
				"company": self.company,
				"currency": self.currency,
				"conversion_rate": 1,
				"transaction_date": nowdate(),
				"valid_till": add_days(nowdate(), 30),
				"items": [{"item_code": "TEST-QA-ITEM", "qty": 1, "rate": rate}],
			}
		)
		doc.insert(ignore_permissions=True)
		apply_workflow(doc, "Submit for Approval")
		return frappe.get_doc("Quotation", doc.name)

	def _approve(self, doc, user, remarks=None):
		frappe.set_user(user)
		set_approval_remarks(doc.name, remarks)
		apply_workflow(frappe.get_doc("Quotation", doc.name), "Approve")
		return frappe.get_doc("Quotation", doc.name)

	def test_approve_with_remarks_keeps_draft(self):
		doc = self._approve(self._quotation(), self.manager, "Change validity to 15 days")
		self.assertEqual(doc.workflow_state, APPROVED)
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(doc.alt_level_1_remarks, "Change validity to 15 days")
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{
					"reference_name": doc.name,
					"comment_type": "Comment",
					"content": ["like", "%validity to 15 days%"],
				},
			)
		)

	def test_owner_edits_details_not_prices(self):
		doc = self._approve(self._quotation(), self.manager, "Add payment terms")
		frappe.set_user(self.owner)
		doc.valid_till = add_days(nowdate(), 15)
		doc.terms = "50% advance"
		doc.save(ignore_permissions=True)  # details: allowed

		doc = frappe.get_doc("Quotation", doc.name)
		doc.items[0].rate = 90
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_other_user_cannot_edit_approved(self):
		doc = self._approve(self._quotation(), self.manager)
		frappe.set_user(self.other)
		doc.terms = "changed by someone else"
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

	def test_send_to_client_submits_and_locks(self):
		doc = self._approve(self._quotation(), self.manager)
		frappe.set_user(self.owner)
		apply_workflow(doc, "Send to Client")
		doc = frappe.get_doc("Quotation", doc.name)
		self.assertEqual(doc.workflow_state, SENT_TO_CLIENT)
		self.assertEqual(doc.docstatus, 1)
		doc.terms = "after sending"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_reject_clears_approval_remarks(self):
		doc = self._quotation()
		frappe.set_user(self.manager)
		set_approval_remarks(doc.name, "draft remark")  # approver opened Approve, then rejected instead
		set_rejection_remarks(doc.name, "Wrong item")
		apply_workflow(frappe.get_doc("Quotation", doc.name), "Reject")
		doc = frappe.get_doc("Quotation", doc.name)
		self.assertEqual(doc.workflow_state, REJECTED)
		self.assertFalse(doc.alt_level_1_remarks)

	def test_level_2_remarks(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD, 50)
		doc = self._approve(self._quotation(rate=100), self.manager, "L1 note")
		self.assertEqual(doc.workflow_state, PENDING_LEVEL_2)
		doc = self._approve(doc, self.director, "L2 note")
		self.assertEqual(doc.workflow_state, APPROVED)
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual((doc.alt_level_1_remarks, doc.alt_level_2_remarks), ("L1 note", "L2 note"))

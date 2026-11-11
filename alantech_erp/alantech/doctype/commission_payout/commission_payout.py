# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Commission Payout: pay the commission of a month / quarter (alantech_erp.sales.commission).

Get Commission: one row per Sales Person with unpaid Commission Ledger Entries in the period (or
just the chosen Sales Person): commissionable sales on their plan's basis, target, achievement,
commission. Adjustments (+ bonus / - deduction) are typed per row.

Submit (= approved; Accounts Manager): the entries are marked paid by this payout and
    Journal Entry      Commission Expense Dr / Commission Payable Cr (per employee as party when
                       the payable account is a Payable account), submitted
    Additional Salary  one per employee with the commission Salary Component, submitted, so the
                       next payroll pays it
Entries posted after Get Commission stop the submit (refresh first), so what is approved is what
is paid. Cancel cancels the Journal Entry / Additional Salaries and frees the entries again.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from alantech_erp.sales import commission, forecast

LEDGER = commission.LEDGER


class CommissionPayout(Document):
	def validate(self):
		self.set_period()
		self.currency = forecast.company_currency(self.company)
		self.set_defaults()
		seen = set()
		for row in self.details:
			if row.sales_person in seen:
				frappe.throw(
					_("Row {0}: {1} is listed twice.").format(row.idx, frappe.bold(row.sales_person))
				)
			seen.add(row.sales_person)
			row.payable_amount = flt(row.commission_amount) + flt(row.adjustment)
		self.total_commission = sum(flt(r.commission_amount) for r in self.details)
		self.total_payable = sum(flt(r.payable_amount) for r in self.details)
		self.validate_accounts()

	def set_period(self):
		start, end = forecast.period_bounds(self.period_type, self.period_start)
		self.from_date, self.to_date = start, end
		self.period_label = forecast.period_label(self.period_type, start)

	def set_defaults(self):
		if not frappe.db.exists("DocType", forecast.SETTINGS):
			return
		s = frappe.get_cached_doc(forecast.SETTINGS)
		self.payout_method = self.payout_method or s.get("payout_method") or commission.PAY_JOURNAL
		for field in ("salary_component", "expense_account", "payable_account", "cost_center"):
			if not self.get(field) and s.get(field):
				self.set(field, s.get(field))
		if not self.cost_center:
			self.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")

	def validate_accounts(self):
		if self.payout_method != commission.PAY_JOURNAL:
			return
		for field in ("expense_account", "payable_account"):
			account = self.get(field)
			if account and frappe.db.get_value("Account", account, "company") != self.company:
				frappe.throw(
					_("{0} {1} belongs to another company.").format(
						_(self.meta.get_label(field)), frappe.bold(account)
					)
				)

	# ------------------------------------------------------------------ rows
	@frappe.whitelist()
	def get_commission(self):
		"""Get Commission button."""
		if self.docstatus != 0:
			frappe.throw(_("Only a draft payout can be refreshed."))
		if not self.is_new():
			self.check_permission("write")
		self.set_period()
		kept = {
			r.sales_person: (r.adjustment, r.remarks) for r in self.details if flt(r.adjustment) or r.remarks
		}
		people = commission.people_with_entries(
			self.company, self.from_date, self.to_date, [self.sales_person] if self.sales_person else None
		)
		self.set("details", [])
		for person in people:
			row, entries = commission.compute_payout_row(person, self.company, self.from_date, self.to_date)
			if not entries:
				continue  # entries only on another basis than the person's plan
			row.adjustment, row.remarks = kept.get(person, (0, None))
			self.append("details", row)
		if not self.details:
			frappe.msgprint(_("No unpaid commission in {0}.").format(self.period_label), alert=True)
		self.validate()
		return self

	# ------------------------------------------------------------------ submit / cancel
	def before_submit(self):
		if not self.details:
			frappe.throw(_("Nothing to pay. Click Get Commission."))
		self._entries = {}
		for row in self.details:
			fresh, entries = commission.compute_payout_row(
				row.sales_person, self.company, self.from_date, self.to_date
			)
			if flt(fresh.base_amount, 2) != flt(row.base_amount, 2) or flt(fresh.commission_amount, 2) != flt(
				row.commission_amount, 2
			):
				frappe.throw(
					_(
						"Row {0}: commission of {1} has changed since it was fetched (new or cancelled transactions). "
						"Click Get Commission and check it again."
					).format(row.idx, frappe.bold(row.sales_person)),
					title=_("Commission Changed"),
				)
			self._entries[row.sales_person] = entries
		if self.payout_method == commission.PAY_SALARY:
			missing = [r.sales_person for r in self.details if not r.employee and flt(r.payable_amount)]
			if missing:
				frappe.throw(
					_("No Employee linked to Sales Person {0}: they cannot be paid through payroll.").format(
						", ".join(frappe.bold(m) for m in missing)
					)
				)

	def on_submit(self):
		for entries in self._entries.values():
			if entries:
				frappe.db.set_value(
					LEDGER, {"name": ["in", entries]}, "commission_payout", self.name, update_modified=False
				)
		if self.payout_method == commission.PAY_JOURNAL:
			self.make_journal_entry()
		else:
			self.make_additional_salaries()

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Payment Ledger Entry", LEDGER)
		if self.journal_entry:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			if je.docstatus == 1:
				je.flags.ignore_permissions = True
				je.cancel()
		for row in self.details:
			if row.additional_salary:
				doc = frappe.get_doc("Additional Salary", row.additional_salary)
				if doc.docstatus == 1:
					doc.flags.ignore_permissions = True
					doc.cancel()
		frappe.db.set_value(
			LEDGER, {"commission_payout": self.name}, "commission_payout", None, update_modified=False
		)

	def make_journal_entry(self):
		rows = [r for r in self.details if flt(r.payable_amount)]
		if not rows:
			return
		party_account = frappe.db.get_value("Account", self.payable_account, "account_type") in (
			"Payable",
			"Receivable",
		)
		je = frappe.new_doc("Journal Entry")
		je.update(
			{
				"voucher_type": "Journal Entry",
				"company": self.company,
				"posting_date": self.posting_date,
				"user_remark": _("Sales commission {0} ({1})").format(self.period_label, self.name),
			}
		)
		for row in rows:
			amount = flt(row.payable_amount, 2)
			debit, credit = (amount, 0) if amount > 0 else (0, -amount)
			je.append(
				"accounts",
				{
					"account": self.expense_account,
					"cost_center": self.cost_center,
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"user_remark": row.sales_person,
				},
			)
			line = {
				"account": self.payable_account,
				"cost_center": self.cost_center,
				"debit_in_account_currency": credit,
				"credit_in_account_currency": debit,
				"user_remark": row.sales_person,
			}
			if party_account and row.employee:
				line.update({"party_type": "Employee", "party": row.employee})
			je.append("accounts", line)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		self.db_set("journal_entry", je.name)

	def make_additional_salaries(self):
		for row in self.details:
			if not flt(row.payable_amount):
				continue
			doc = frappe.new_doc("Additional Salary")
			doc.update(
				{
					"employee": row.employee,
					"company": self.company,
					"salary_component": self.salary_component,
					"amount": abs(flt(row.payable_amount, 2)),
					"payroll_date": self.posting_date,
					"overwrite_salary_structure_amount": 0,
					"ref_doctype": self.doctype,
					"ref_docname": self.name,
				}
			)
			if flt(row.payable_amount) < 0:
				# a net clawback: deducted from the salary
				doc.salary_component = _deduction_component(self.salary_component)
			doc.flags.ignore_permissions = True
			doc.insert()
			doc.submit()
			row.db_set("additional_salary", doc.name)


def _deduction_component(earning):
	"""A clawback needs a Deduction component: '<earning> Recovery', created when missing."""
	name = f"{earning} Recovery"
	if not frappe.db.exists("Salary Component", name):
		frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": name,
				"salary_component_abbr": "COMR",
				"type": "Deduction",
			}
		).insert(ignore_permissions=True)
	return name

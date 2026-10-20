import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class OvertimeLog(Document):
	def validate(self):
		self.validate_values()
		self.validate_duplicate()
		self.calculate_amount()

	def validate_values(self):
		if self.set_amount_manually:
			if flt(self.overtime_amount) <= 0:
				frappe.throw(_("Overtime Amount must be greater than zero."))
			if flt(self.overtime_hours) < 0 or flt(self.overtime_rate) < 0:
				frappe.throw(_("Overtime Hours and Rate cannot be negative."))
		else:
			if flt(self.overtime_hours) <= 0:
				frappe.throw(_("Overtime Hours must be greater than zero."))
			if flt(self.overtime_rate) <= 0:
				frappe.throw(_("Overtime Rate must be greater than zero."))

	def validate_duplicate(self):
		duplicate = frappe.db.exists(
			"Overtime Log",
			{
				"employee": self.employee,
				"overtime_date": self.overtime_date,
				"project": self.project,
				"docstatus": ["!=", 2],
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("Overtime Log {0} already exists for {1} on {2} for project {3}.").format(
					frappe.bold(duplicate),
					frappe.bold(self.employee),
					frappe.bold(self.overtime_date),
					frappe.bold(self.project),
				),
				title=_("Duplicate Overtime Log"),
			)

	def calculate_amount(self):
		if self.set_amount_manually:
			return
		self.overtime_amount = flt(
			flt(self.overtime_hours) * flt(self.overtime_rate),
			self.precision("overtime_amount"),
		)
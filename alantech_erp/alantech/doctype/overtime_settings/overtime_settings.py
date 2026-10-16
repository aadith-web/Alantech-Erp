import frappe
from frappe import _
from frappe.model.document import Document


class OvertimeSettings(Document):
    def validate(self):
        if not self.working_hours_per_day or not (0 < self.working_hours_per_day <= 24):
            frappe.throw(_("Working Hours Per Day must be greater than 0 and not more than 24."))

        if not self.enable_multiple_ot:
            return

        if not self.overtime_type_rules:
            frappe.throw(_("Add at least one row in Overtime Type Rules."))

        seen = set()
        for row in self.overtime_type_rules:
            if row.ot_type in seen:
                frappe.throw(_("Row #{0}: OT Type {1} is already defined.").format(
                    row.idx, frappe.bold(row.ot_type)))
            seen.add(row.ot_type)
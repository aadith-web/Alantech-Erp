import frappe
from frappe import _
from frappe.model.document import Document


class PolicyCategory(Document):
    def validate(self):
        self.category_name = (self.category_name or "").strip()
        if not self.category_name:
            frappe.throw(_("Category Name is required."))
"""Delete ERPNext's sample designations (Analyst, Manager, Software Developer, ...): only the posts
of the organisation chart AIS-MS-TP-01 (org_structure.DESIGNATIONS) and the ones added after it
(setup/designations.EXTRA_DESIGNATIONS) are used. A designation still linked to a record (an
employee, a loan rule, ...) is kept and listed, to be moved to a chart post by HR first.
"""

import frappe

from alantech_erp.org_structure import DESIGNATIONS
from alantech_erp.setup.designations import EXTRA_DESIGNATIONS


def execute():
	keep = {row[0] for row in DESIGNATIONS} | {row[0] for row in EXTRA_DESIGNATIONS}
	deleted, kept = [], []
	for name in frappe.get_all("Designation", pluck="name"):
		if name in keep:
			continue
		try:
			frappe.delete_doc("Designation", name, ignore_permissions=True)
			deleted.append(name)
		except frappe.LinkExistsError:
			frappe.clear_messages()
			kept.append(name)
	print(f"Sample designations deleted: {len(deleted)}; still linked, kept: {', '.join(kept) or '-'}")

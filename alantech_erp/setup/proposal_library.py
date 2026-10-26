"""Standard water treatment library: Sub Assemblies, Plant Assemblies, terms and proposal texts.

Data: setup/data/water_treatment_library.json, taken from the costing workbook
("Water Treatment costing template 2026") and the UF + RO + EDI 160 m³/h proposal.

    bench --site <site> execute alantech_erp.setup.proposal_library.load

Only adds what is missing; records that already exist (same name) are left as they are, so edits
made in the system are never overwritten. Runs once automatically after migrate.
"""

import json
import os

import frappe

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "water_treatment_library.json")


def load():
	with open(DATA_FILE, encoding="utf-8") as f:
		data = json.load(f)

	counts = {"terms": 0, "sub_assemblies": 0, "plant_assemblies": 0}

	for terms in data.get("terms", []):
		if frappe.db.exists("Terms and Conditions", terms["title"]):
			continue
		frappe.get_doc({"doctype": "Terms and Conditions", "selling": 1, **terms}).insert(ignore_permissions=True)
		counts["terms"] += 1

	for sub in data.get("sub_assemblies", []):
		if frappe.db.exists("Sub Assembly", sub["sub_assembly_name"]):
			continue
		doc = frappe.get_doc({"doctype": "Sub Assembly", **sub})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		counts["sub_assemblies"] += 1

	for assembly in data.get("plant_assemblies", []):
		if frappe.db.exists("Plant Assembly", assembly["assembly_name"]):
			continue
		doc = frappe.get_doc({"doctype": "Plant Assembly", **assembly})
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		counts["plant_assemblies"] += 1

	settings = frappe.get_single("Proposal Settings")
	for field, value in (data.get("settings") or {}).items():
		if field == "bought_out_items":
			if not settings.bought_out_items:
				settings.set(field, value)
		elif not settings.get(field):
			settings.set(field, value)
	settings.library_loaded = 1
	settings.flags.ignore_permissions = True
	settings.flags.ignore_links = True
	settings.save()
	return counts

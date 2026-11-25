# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Asset: Grouped Asset / Single Asset for the Asset Quantity (ClickUp 14yr2e58hv1).

"Create As" (alt_asset_creation, a Select, so only one option at a time), next to Asset Quantity:
- Grouped Asset (default, ERPNext's standard): Asset Quantity N is one Asset with quantity N.
- Single Asset: Asset Quantity N becomes N Assets of quantity 1. The submitted Asset is the first one;
  a background job (queue "long") splits the other N - 1 units off it with ERPNext's own Split Asset
  (asset.split_asset), one unit at a time, so the Net Purchase Amount, Opening Accumulated
  Depreciation, finance books and depreciation schedules are shared out as ERPNext does, and each new
  Asset has "Split From" = the first one. The submit is not held up. The job splits only what is
  left (the first Asset's quantity above 1), so running it again (the form's "Create Remaining
  Assets" button) never makes too many.
- The form shows the progress ("n of N assets created") and links to the assets.

Hooked: Asset on_submit (hooks.py doc_events); the field is created by execute() after_migrate.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

FIELD = "alt_asset_creation"
GROUPED, SINGLE = "Grouped Asset", "Single Asset"

FIELDS = {
	"Asset": [
		{
			"fieldname": FIELD,
			"label": "Create As",
			"fieldtype": "Select",
			"options": f"{GROUPED}\n{SINGLE}",
			"default": GROUPED,
			"insert_after": "asset_quantity",
			"read_only_depends_on": "eval:doc.docstatus>0",
			"no_copy": 1,
			"allow_on_submit": 0,
			"description": "Grouped Asset: the quantity is one asset (e.g. 10 = 1 asset of quantity 10). "
			"Single Asset: one asset per unit (e.g. 10 = 10 assets of quantity 1); the first is this asset, "
			"the others are created in the background after submit.",
		},
	]
}


def execute():
	if frappe.db.exists("DocType", "Asset"):
		create_custom_fields(FIELDS, update=True)


def is_single(doc):
	return doc.get(FIELD) == SINGLE


def on_submit(doc, method=None):
	if is_single(doc) and cint(doc.asset_quantity) > 1:
		enqueue(doc.name)


def enqueue(asset):
	frappe.enqueue(
		"alantech_erp.setup.asset_creation_mode.split_into_single_assets",
		queue="long",
		timeout=3600,
		job_id=f"alt_single_assets::{asset}",
		deduplicate=True,
		enqueue_after_commit=True,
		asset=asset,
	)


def split_into_single_assets(asset):
	"""Split units off `asset` until it has quantity 1. Returns the number of assets created."""
	from erpnext.assets.doctype.asset.asset import split_asset

	made = 0
	while True:
		doc = frappe.get_doc("Asset", asset)
		if doc.docstatus != 1 or not is_single(doc) or cint(doc.asset_quantity) <= 1:
			return made
		try:
			split_asset(asset, 1)
			made += 1
			if not frappe.in_test:
				frappe.db.commit()  # keep each asset made, whatever happens to the next one
		except Exception:
			if not frappe.in_test:
				frappe.db.rollback()
			frappe.log_error(title=_("Single Asset: could not create the next asset from {0}").format(asset))
			return made


def split_count(asset):
	return frappe.db.count("Asset", {"split_from": asset, "docstatus": ["<", 2]})


@frappe.whitelist()
def get_single_asset_status(asset):
	doc = frappe.get_doc("Asset", asset)
	doc.check_permission("read")
	if not is_single(doc):
		return None
	created = split_count(asset)
	return {"created": created + 1, "total": created + cint(doc.asset_quantity), "remaining": cint(doc.asset_quantity) - 1}


@frappe.whitelist()
def create_remaining_assets(asset):
	doc = frappe.get_doc("Asset", asset)
	doc.check_permission("submit")
	if doc.docstatus != 1 or not is_single(doc) or cint(doc.asset_quantity) <= 1:
		frappe.throw(_("Nothing left to create: this is not a submitted Single Asset with a quantity above 1."))
	enqueue(asset)

# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Asset: Opening Stock for an Existing Asset, one Asset per unit (ClickUp 14yr2e58hv1).

- Opening Stock (alt_opening_stock) is shown only when Asset Type = Existing Asset (cleared for the
  other types). It is the number of units already owned; every unit becomes its own Asset, with the
  values entered on this one (Net Purchase Amount, Opening Accumulated Depreciation, ... are per
  unit), so Asset Quantity is kept at 1.
- On submit of an Existing Asset with Opening Stock N > 1, this Asset is the first unit (created
  at once, by the submit itself) and a background job (queue "long") creates and submits the other
  N - 1 Assets, each a copy of this one with Opening Stock 0 and "Opening Stock Of" = this Asset.
  The submit is not held up. The job only makes what is still missing, so running it again (the
  form's "Create Missing Assets" button) never makes too many.
- The form shows the progress: "n of N assets created" with a link to them.

Hooked: Asset validate / on_submit (hooks.py doc_events); fields created by execute() after_migrate.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

EXISTING = "Existing Asset"
FIELD = "alt_opening_stock"
SOURCE = "alt_opening_stock_of"

FIELDS = {
	"Asset": [
		{
			"fieldname": FIELD,
			"label": "Opening Stock",
			"fieldtype": "Int",
			"insert_after": "asset_type",
			"depends_on": f'eval:doc.asset_type=="{EXISTING}"',
			"read_only_depends_on": "eval:doc.docstatus>0",
			"no_copy": 1,
			"non_negative": 1,
			"description": "Units already owned. On submit this asset is the first unit and the others are "
			"created in the background, one asset per unit, with the same values (enter the amounts for one unit).",
		},
		{
			"fieldname": SOURCE,
			"label": "Opening Stock Of",
			"fieldtype": "Link",
			"options": "Asset",
			"insert_after": FIELD,
			"read_only": 1,
			"no_copy": 1,
			"depends_on": SOURCE,
			"search_index": 1,
			"description": "Created from the Opening Stock of this asset.",
		},
	]
}


def execute():
	if frappe.db.exists("DocType", "Asset"):
		create_custom_fields(FIELDS, update=True)


def units(doc):
	"""Opening Stock that counts: only for an Existing Asset."""
	return cint(doc.get(FIELD)) if doc.get("asset_type") == EXISTING else 0


def validate(doc, method=None):
	if doc.get("asset_type") != EXISTING:
		doc.set(FIELD, 0)
	elif cint(doc.get(FIELD)) < 0:
		frappe.throw(_("Opening Stock cannot be negative."), title=_("Opening Stock"))
	elif cint(doc.get(FIELD)) > 1:
		doc.asset_quantity = 1  # one asset per unit


def on_submit(doc, method=None):
	if units(doc) > 1:
		enqueue(doc.name)


def enqueue(asset):
	frappe.enqueue(
		"alantech_erp.setup.asset_opening_stock.create_opening_assets",
		queue="long",
		timeout=3600,
		job_id=f"alt_opening_stock::{asset}",
		deduplicate=True,
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
		asset=asset,
	)


def created_count(asset):
	return frappe.db.count("Asset", {SOURCE: asset, "docstatus": ["<", 2]})


def create_opening_assets(asset):
	"""Create and submit the Assets still missing for the Opening Stock of `asset`."""
	source = frappe.get_doc("Asset", asset)
	if source.docstatus != 1:
		return 0
	missing = units(source) - 1 - created_count(asset)
	made = 0
	for _i in range(max(missing, 0)):
		try:
			copy = frappe.copy_doc(source)
			copy.update({FIELD: 0, SOURCE: source.name, "asset_quantity": 1})
			copy.insert()
			copy.submit()
			made += 1
			if not frappe.flags.in_test:
				frappe.db.commit()  # keep each unit made, whatever happens to the next one
		except Exception:
			if not frappe.flags.in_test:
				frappe.db.rollback()
			frappe.log_error(title=_("Opening Stock: asset not created for {0}").format(asset))
			break
	return made


@frappe.whitelist()
def get_opening_stock_status(asset):
	doc = frappe.get_doc("Asset", asset)
	doc.check_permission("read")
	total = units(doc)
	return {"total": total, "created": 1 + created_count(asset) if total else 0}


@frappe.whitelist()
def create_missing_assets(asset):
	doc = frappe.get_doc("Asset", asset)
	doc.check_permission("submit")
	if doc.docstatus != 1 or units(doc) <= 1:
		frappe.throw(_("Only a submitted Existing Asset with an Opening Stock above 1 creates assets."))
	enqueue(asset)

"""Employee Asset Handover: one simple form for HR to issue assets to an employee or take them back.

On submit it creates and submits the standard ERPNext Asset Movement (Issue / Receipt), so the
Asset's Custodian and Location stay correct and the Full and Final Statement sees the right
assets. On a Receipt, assets marked Damaged during inspection get an Asset Repair (Pending),
which is where damage is tracked and reported (Responsible Employee is a custom field on it).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, get_link_to_form, nowdate

ISSUE, RECEIPT = "Issue", "Receipt"
CLOSED_ASSET_STATUSES = ("Sold", "Scrapped")
HANDOVER_ROLES = {"System Manager", "HR Manager", "HR User"}


class EmployeeAssetHandover(Document):
	def validate(self):
		self.validate_employee()
		self.clear_fields_for_type()
		self.validate_items()
		self.validate_inspection()

	def on_submit(self):
		self.make_asset_movement()
		if self.transaction_type == RECEIPT:
			self.make_asset_repairs()

	def before_cancel(self):
		self.check_later_movements()
		submitted = [r.asset_repair for r in self.items
		             if r.asset_repair and frappe.db.get_value("Asset Repair", r.asset_repair, "docstatus") == 1]
		if submitted:
			frappe.throw(_("Cancel the submitted Asset Repair {0} first.").format(
				", ".join(get_link_to_form("Asset Repair", n) for n in submitted)))

	def on_cancel(self):
		# the Asset Movement / Asset Repair created here are removed below, so they must not block the cancel
		self.ignore_linked_doctypes = ("Asset Movement", "Asset Repair")
		self.remove_draft_repairs()
		self.cancel_asset_movement()

	# --- validation ------------------------------------------------------
	def validate_employee(self):
		status = frappe.db.get_value("Employee", self.employee, "status")
		if self.transaction_type == ISSUE and status != "Active":
			frappe.throw(_("Assets can only be issued to an Active employee. {0} is {1}.").format(
				self.employee_name or self.employee, _(status)))

	def clear_fields_for_type(self):
		if self.transaction_type == ISSUE:
			self.location = None
			self.inspection_required = 0
		if not self.inspection_required:
			self.inspected_by = self.inspection_date = self.inspection_remarks = None
			for row in self.items:
				row.condition = None
				row.issue_description = None

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Add at least one asset."))
		if self.transaction_type == RECEIPT and not self.location:
			frappe.throw(_("Return To Location is required to receive assets."))

		seen = set()
		for row in self.items:
			if row.asset in seen:
				frappe.throw(_("Row {0}: Asset {1} is added more than once.").format(row.idx, row.asset))
			seen.add(row.asset)

			asset = frappe.db.get_value("Asset", row.asset,
			                            ["asset_name", "company", "location", "custodian", "status", "docstatus"],
			                            as_dict=True)
			if not asset:
				frappe.throw(_("Row {0}: Asset {1} does not exist.").format(row.idx, row.asset))
			row.asset_name = asset.asset_name
			row.current_location = asset.location
			label = f"{row.asset} ({asset.asset_name})"

			if asset.docstatus != 1:
				frappe.throw(_("Row {0}: Asset {1} is not submitted yet.").format(row.idx, label))
			if asset.company != self.company:
				frappe.throw(_("Row {0}: Asset {1} belongs to {2}, but the employee belongs to {3}.").format(
					row.idx, label, asset.company, self.company))
			if asset.status in CLOSED_ASSET_STATUSES:
				frappe.throw(_("Row {0}: Asset {1} is {2}.").format(row.idx, label, _(asset.status)))

			if self.transaction_type == ISSUE:
				if asset.custodian == self.employee:
					frappe.throw(_("Row {0}: Asset {1} is already with {2}.").format(
						row.idx, label, self.employee_name or self.employee))
				if asset.custodian:
					holder = frappe.db.get_value("Employee", asset.custodian, "employee_name") or asset.custodian
					frappe.throw(_("Row {0}: Asset {1} is currently issued to {2} ({3}). Receive it back first.").format(
						row.idx, label, holder, asset.custodian))
				if asset.status == "Out of Order":
					frappe.throw(_("Row {0}: Asset {1} is Out of Order (under repair) and cannot be issued.").format(
						row.idx, label))
			elif asset.custodian != self.employee:
				frappe.throw(_("Row {0}: Asset {1} is not issued to {2}.").format(
					row.idx, label, self.employee_name or self.employee))

			self.validate_after_last_movement(row, label)

	def validate_after_last_movement(self, row, label):
		"""Asset Movement rejects a date earlier than the asset's last movement; say so in plain words."""
		last = frappe.db.get_value(
			"Asset Movement",
			[["Asset Movement Item", "asset", "=", row.asset], ["docstatus", "=", 1]],
			"transaction_date", order_by="transaction_date desc")
		if last and get_datetime(last) > get_datetime(self.transaction_date):
			frappe.throw(_("Row {0}: Asset {1} was last moved on {2}. The Date cannot be earlier than that.").format(
				row.idx, label, frappe.format(last, "Datetime")))

	def validate_inspection(self):
		if self.transaction_type != RECEIPT or not self.inspection_required:
			return
		self.inspected_by = self.inspected_by or frappe.session.user
		self.inspection_date = self.inspection_date or nowdate()
		for row in self.items:
			if not row.condition:
				frappe.throw(_("Row {0}: select the Condition of asset {1} (Good or Damaged).").format(row.idx, row.asset))
			if row.condition == "Damaged" and not (row.issue_description or "").strip():
				frappe.throw(_("Row {0}: describe the damage of asset {1}.").format(row.idx, row.asset))

	# --- submit ----------------------------------------------------------
	def make_asset_movement(self):
		movement = frappe.new_doc("Asset Movement")
		movement.update({
			"company": self.company,
			"purpose": self.transaction_type,
			"transaction_date": self.transaction_date,
			"reference_doctype": self.doctype,
			"reference_name": self.name,
		})
		for row in self.items:
			item = {"asset": row.asset, "asset_name": row.asset_name, "company": self.company,
			        "source_location": row.current_location}
			if self.transaction_type == ISSUE:
				item["to_employee"] = self.employee
			else:
				item["from_employee"] = self.employee
				item["target_location"] = self.location
			movement.append("assets", item)

		# HR may not have rights on Asset Movement; the handover itself is the permission check
		movement.flags.ignore_permissions = True
		movement.insert()
		movement.submit()
		self.db_set("asset_movement", movement.name)

	def make_asset_repairs(self):
		created = []
		for row in self.items:
			if row.condition != "Damaged":
				continue
			repair = frappe.new_doc("Asset Repair")
			repair.update({
				"asset": row.asset,
				"company": self.company,
				"failure_date": self.transaction_date,
				"repair_status": "Pending",
				"description": _("Reported on return by {0} ({1}) in {2}.").format(
					self.employee_name, self.employee, self.name) + "\n\n" + row.issue_description.strip(),
				"alt_responsible_employee": self.employee,
				"alt_employee_asset_handover": self.name,
			})
			repair.flags.ignore_permissions = True
			repair.insert()   # stays Draft / Pending: the Asset shows as Out of Order until repaired
			row.db_set("asset_repair", repair.name)
			created.append(repair.name)
		if created:
			frappe.msgprint(
				_("Asset Repair created for the damaged assets: {0}").format(
					", ".join(get_link_to_form("Asset Repair", n) for n in created)),
				title=_("Damage Reported"), indicator="orange")

	# --- cancel ----------------------------------------------------------
	def check_later_movements(self):
		"""Cancelling an older movement while a newer one exists would put the wrong custodian on the asset."""
		if not self.asset_movement:
			return
		this_date = frappe.db.get_value("Asset Movement", self.asset_movement, "transaction_date")
		for row in self.items:
			later = frappe.db.get_value(
				"Asset Movement",
				[["Asset Movement Item", "asset", "=", row.asset], ["docstatus", "=", 1],
				 ["name", "!=", self.asset_movement], ["transaction_date", ">=", this_date]],
				"name")
			if later:
				frappe.throw(_("Asset {0} has a later movement {1}. Cancel that first.").format(
					row.asset, get_link_to_form("Asset Movement", later)))

	def remove_draft_repairs(self):
		for row in self.items:
			if row.asset_repair and frappe.db.get_value("Asset Repair", row.asset_repair, "docstatus") == 0:
				name = row.asset_repair
				row.db_set("asset_repair", None)   # unlink first, or delete_doc refuses
				frappe.delete_doc("Asset Repair", name, ignore_permissions=True)   # resets the Asset status

	def cancel_asset_movement(self):
		if self.asset_movement and frappe.db.get_value("Asset Movement", self.asset_movement, "docstatus") == 1:
			movement = frappe.get_doc("Asset Movement", self.asset_movement)
			movement.flags.ignore_permissions = True
			movement.flags.ignore_links = True
			movement.cancel()   # restores the previous custodian and location on the Asset


# --- helpers used by the form, the Employee form, the report and the exit alerts ---------
def check_handover_access():
	if not (HANDOVER_ROLES & set(frappe.get_roles())) and frappe.session.user != "Administrator":
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def get_assets_held(employee):
	"""Assets whose Custodian is this employee (what the Full and Final Statement will list)."""
	return frappe.get_all(
		"Asset",
		filters={"custodian": employee, "docstatus": 1, "status": ["not in", CLOSED_ASSET_STATUSES]},
		fields=["name as asset", "asset_name", "location", "status"],
		order_by="asset_name asc",
	)


@frappe.whitelist()
def get_employee_assets(employee):
	check_handover_access()
	return get_assets_held(employee)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def asset_query(doctype, txt, searchfield, start, page_len, filters):
	"""Asset picker: free assets for Issue, the employee's assets for Receipt.
	Works for HR users who have no read access on Asset."""
	check_handover_access()
	filters = frappe._dict(filters or {})
	conditions = {"docstatus": 1, "status": ["not in", CLOSED_ASSET_STATUSES]}
	if filters.company:
		conditions["company"] = filters.company
	if filters.transaction_type == RECEIPT:
		conditions["custodian"] = filters.employee or "__none__"
	else:
		conditions["custodian"] = ["is", "not set"]
		conditions["status"] = ["not in", (*CLOSED_ASSET_STATUSES, "Out of Order")]
	txt = f"%{txt}%"
	return frappe.get_all(
		"Asset", filters=conditions,
		or_filters=[["name", "like", txt], ["asset_name", "like", txt], ["item_code", "like", txt]],
		fields=["name", "asset_name", "location"],
		order_by="asset_name asc", limit_start=start, limit_page_length=page_len, as_list=True,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def location_query(doctype, txt, searchfield, start, page_len, filters):
	check_handover_access()
	return frappe.get_all(
		"Location", filters={"name": ["like", f"%{txt}%"]},
		fields=["name"], order_by="name asc",
		limit_start=start, limit_page_length=page_len, as_list=True,
	)

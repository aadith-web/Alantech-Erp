"""Employee Asset Handover: one simple form for HR to issue assets to an employee or take them back.

On submit it creates and submits the standard ERPNext Asset Movement (Issue / Receipt), so the
Asset's Custodian and Location stay correct and the Full and Final Statement sees the right
assets. On a Receipt, assets marked Damaged during inspection get an Asset Repair (Pending),
which is where damage is tracked and reported (Responsible Employee is a custom field on it).

Quantity (ClickUp 14yr2e58hbm): each row has a Quantity, and the asset picker and the row show the
Available Qty.
- Single asset (Asset Quantity 1): as above (Custodian, Asset Movement); Quantity is always 1.
- Grouped asset (Asset Quantity above 1, e.g. 5 Mobiles in one Asset record): ERPNext allows one
  Custodian per Asset, so the quantities are tracked by the submitted handovers instead (agreed with
  HR; no Split Asset, no accounting entries). Available = Asset Quantity - issued and not returned;
  an employee holds Issue qty - Receipt qty. No Asset Movement for these rows; cancelling a handover
  gives the quantity back (refused when that would make a holding negative).
- Issue: Quantity up to the Available Qty; Receipt: up to what the employee holds.
- The employee's assets (Receipt, Employee form, exit alerts, Employee Asset Holdings) include the
  grouped holdings with their quantity.

Return To Location per asset (ClickUp 14yr2e58hwg): on a Receipt each row has its own Return To
Location (filled with the asset's Current Location when the asset is picked, editable), so assets of
one receipt can go to different locations; required for every row of a Receipt, cleared on an Issue.
The Asset Movement moves each single asset to its row's location. Replaces the form-level field
(patches/v16/handover_return_location_per_row.py copied it to the rows of existing receipts).

Condition per asset (ClickUp 14yr2e58jx0): every row of every handover has a Condition, Good or
Damaged (default Good), not only a Receipt with "Inspect Assets on Return" ticked. Damaged needs the
Damage Details. Issue: the condition the asset was handed over in (recorded only). Receipt: a Damaged
asset gets an Asset Repair (Pending) on submit, with or without the inspection tick; the tick only adds
Inspected By / Date / Remarks.

Total Assets (ClickUp 14yr2e58jwz): the number of assets (rows with an asset), kept on the form and
shown as a column in the list (patches/v16/handover_total_assets_count.py filled it on existing handovers).

Assets table on a new form (ClickUp 14yr2e58jwx): not marked mandatory (an empty mandatory table has a
red border that looks like an error); a new Issue starts with one empty row to fill; saving without
an asset is refused on the server: "Add at least one asset in the Assets table."
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, get_link_to_form, nowdate

ISSUE, RECEIPT = "Issue", "Receipt"
GOOD, DAMAGED = "Good", "Damaged"
CLOSED_ASSET_STATUSES = ("Sold", "Scrapped")
HANDOVER_ROLES = {"System Manager", "HR Manager", "HR User"}


def total_assets(rows):
	return sum(1 for r in rows or [] if r.get("asset"))


class EmployeeAssetHandover(Document):
	def validate(self):
		self.validate_employee()
		self.clear_fields_for_type()
		self.validate_items()
		self.validate_inspection()
		self.total_assets = total_assets(self.items)

	def on_submit(self):
		self.make_asset_movement()
		if self.transaction_type == RECEIPT:
			self.make_asset_repairs()

	def before_cancel(self):
		self.check_later_movements()
		self.check_grouped_cancel()
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
			self.inspection_required = 0
			for row in self.items:
				row.return_location = None
		if not self.inspection_required:
			self.inspected_by = self.inspection_date = self.inspection_remarks = None
		for row in self.items:
			row.condition = row.condition or GOOD
			if row.condition != DAMAGED:
				row.issue_description = None

	def validate_items(self):
		# an empty row left over (e.g. the first row a new Issue starts with) is dropped
		self.set("items", [r for r in self.items if r.asset])
		for idx, row in enumerate(self.items, 1):
			row.idx = idx
		if not self.items:
			frappe.throw(_("Add at least one asset in the Assets table."), title=_("No Assets"))

		seen = set()
		for row in self.items:
			if row.asset in seen:
				frappe.throw(_("Row {0}: Asset {1} is added more than once.").format(row.idx, row.asset))
			seen.add(row.asset)

			asset = frappe.db.get_value("Asset", row.asset,
			                            ["asset_name", "company", "location", "custodian", "status", "docstatus",
			                             "asset_quantity"],
			                            as_dict=True)
			if not asset:
				frappe.throw(_("Row {0}: Asset {1} does not exist.").format(row.idx, row.asset))
			row.asset_name = asset.asset_name
			row.current_location = asset.location
			label = f"{row.asset} ({asset.asset_name})"
			if self.transaction_type == RECEIPT and not row.return_location:
				frappe.throw(_("Row {0}: select the Return To Location for asset {1}.").format(row.idx, label),
					title=_("Return To Location Missing"))

			if asset.docstatus != 1:
				frappe.throw(_("Row {0}: Asset {1} is not submitted yet.").format(row.idx, label))
			if asset.company != self.company:
				frappe.throw(_("Row {0}: Asset {1} belongs to {2}, but the employee belongs to {3}.").format(
					row.idx, label, asset.company, self.company))
			if asset.status in CLOSED_ASSET_STATUSES:
				frappe.throw(_("Row {0}: Asset {1} is {2}.").format(row.idx, label, _(asset.status)))
			if self.transaction_type == ISSUE and asset.status == "Out of Order":
				frappe.throw(_("Row {0}: Asset {1} is Out of Order (under repair) and cannot be issued.").format(
					row.idx, label))

			if is_grouped(asset):
				self.validate_grouped_row(row, asset, label)
				continue

			if cint(row.qty) != 1:
				frappe.throw(_("Row {0}: Asset {1} is a single asset; its Quantity must be 1.").format(row.idx, label))
			row.available_qty = available_qty(row.asset, self.transaction_type, self.employee, asset)
			if self.transaction_type == ISSUE:
				if asset.custodian == self.employee:
					frappe.throw(_("Row {0}: Asset {1} is already with {2}.").format(
						row.idx, label, self.employee_name or self.employee))
				if asset.custodian:
					holder = frappe.db.get_value("Employee", asset.custodian, "employee_name") or asset.custodian
					frappe.throw(_("Row {0}: Asset {1} is currently issued to {2} ({3}). Receive it back first.").format(
						row.idx, label, holder, asset.custodian))
			elif asset.custodian != self.employee:
				frappe.throw(_("Row {0}: Asset {1} is not issued to {2}.").format(
					row.idx, label, self.employee_name or self.employee))

			self.validate_after_last_movement(row, label)

	def validate_grouped_row(self, row, asset, label):
		"""Quantity of a grouped asset against what is available (Issue) or held (Receipt)."""
		qty = cint(row.qty)
		if qty <= 0:
			frappe.throw(_("Row {0}: enter a Quantity above 0 for asset {1}.").format(row.idx, label))
		row.available_qty = available_qty(row.asset, self.transaction_type, self.employee, asset)
		if self.transaction_type == ISSUE:
			if qty > row.available_qty:
				frappe.throw(_("Row {0}: only {1} of asset {2} available (Asset Quantity {3}); you entered {4}.").format(
					row.idx, row.available_qty, label, cint(asset.asset_quantity), qty),
					title=_("Quantity Not Available"))
		elif row.available_qty <= 0:
			frappe.throw(_("Row {0}: Asset {1} is not issued to {2}.").format(
				row.idx, label, self.employee_name or self.employee))
		elif qty > row.available_qty:
			frappe.throw(_("Row {0}: {1} holds only {2} of asset {3}; you entered {4}.").format(
				row.idx, self.employee_name or self.employee, row.available_qty, label, qty),
				title=_("Quantity Not Available"))

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
		for row in self.items:
			if row.condition not in (GOOD, DAMAGED):
				frappe.throw(_("Row {0}: select the Condition of asset {1} (Good or Damaged).").format(row.idx, row.asset))
			if row.condition == DAMAGED and not (row.issue_description or "").strip():
				frappe.throw(_("Row {0}: describe the damage of asset {1} in Damage Details.").format(row.idx, row.asset),
					title=_("Damage Details Missing"))
		if self.transaction_type == RECEIPT and self.inspection_required:
			self.inspected_by = self.inspected_by or frappe.session.user
			self.inspection_date = self.inspection_date or nowdate()

	# --- submit ----------------------------------------------------------
	def make_asset_movement(self):
		rows = [r for r in self.items if not is_grouped_asset(r.asset)]
		if not rows:  # grouped assets only: tracked by this handover's quantities
			return
		movement = frappe.new_doc("Asset Movement")
		movement.update({
			"company": self.company,
			"purpose": self.transaction_type,
			"transaction_date": self.transaction_date,
			"reference_doctype": self.doctype,
			"reference_name": self.name,
		})
		for row in rows:
			item = {"asset": row.asset, "asset_name": row.asset_name, "company": self.company,
			        "source_location": row.current_location}
			if self.transaction_type == ISSUE:
				item["to_employee"] = self.employee
			else:
				item["from_employee"] = self.employee
				item["target_location"] = row.return_location
			movement.append("assets", item)

		# HR may not have rights on Asset Movement; the handover itself is the permission check
		movement.flags.ignore_permissions = True
		movement.insert()
		movement.submit()
		self.db_set("asset_movement", movement.name)

	def make_asset_repairs(self):
		created = []
		for row in self.items:
			if row.condition != DAMAGED:
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
			if is_grouped_asset(row.asset):
				continue
			later = frappe.db.get_value(
				"Asset Movement",
				[["Asset Movement Item", "asset", "=", row.asset], ["docstatus", "=", 1],
				 ["name", "!=", self.asset_movement], ["transaction_date", ">=", this_date]],
				"name")
			if later:
				frappe.throw(_("Asset {0} has a later movement {1}. Cancel that first.").format(
					row.asset, get_link_to_form("Asset Movement", later)))

	def check_grouped_cancel(self):
		"""Cancelling must not leave a negative holding: an Issue whose units were already received
		back, or a Receipt whose units were issued again."""
		for row in self.items:
			if not is_grouped_asset(row.asset):
				continue
			label = f"{row.asset} ({row.asset_name})"
			qty = cint(row.qty) or 1
			if self.transaction_type == ISSUE:
				held = held_qty(row.asset).get(self.employee, 0)
				if held < qty:
					frappe.throw(_("Asset {0}: {1} of the {2} issued here were already received back. Cancel that Receipt first.").format(
						label, qty - held, qty))
			else:
				free = available_qty(row.asset, ISSUE)
				if free < qty:
					frappe.throw(_("Asset {0}: {1} of the {2} received here were issued again. Cancel that Issue first.").format(
						label, qty - free, qty))

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


# --- quantities (ClickUp 14yr2e58hbm) ---------------------------------------------------
def is_grouped(asset):
	return cint(asset.get("asset_quantity")) > 1


def is_grouped_asset(name):
	return cint(frappe.db.get_value("Asset", name, "asset_quantity")) > 1


def held_qty(asset_names, employee=None):
	"""Grouped assets: quantity held per employee from submitted handovers (Issue - Receipt).
	One asset name -> {employee: qty}; a list -> {(asset, employee): qty}. Only quantities above 0."""
	single = isinstance(asset_names, str)
	names = [asset_names] if single else list(asset_names)
	if not names:
		return {}
	conditions = "and h.employee = %(employee)s" if employee else ""
	rows = frappe.db.sql(
		f"""
		select i.asset, h.employee,
			sum(case when h.transaction_type = 'Issue' then ifnull(nullif(i.qty, 0), 1)
				else -ifnull(nullif(i.qty, 0), 1) end) as qty
		from `tabEmployee Asset Handover Item` i
		join `tabEmployee Asset Handover` h on h.name = i.parent
		where h.docstatus = 1 and i.parenttype = 'Employee Asset Handover' and i.asset in %(names)s {conditions}
		group by i.asset, h.employee
		""",
		{"names": names, "employee": employee},
		as_dict=True,
	)
	if single:
		return {r.employee: cint(r.qty) for r in rows if cint(r.qty) > 0}
	return {(r.asset, r.employee): cint(r.qty) for r in rows if cint(r.qty) > 0}


def available_qty(name, transaction_type=ISSUE, employee=None, asset=None):
	"""Issue: quantity not issued to anyone. Receipt: quantity `employee` holds."""
	asset = asset or frappe.db.get_value("Asset", name, ["asset_quantity", "custodian", "status"], as_dict=True)
	if not asset:
		return 0
	if is_grouped(asset):
		held = held_qty(name)
		if transaction_type == RECEIPT:
			return held.get(employee, 0)
		return max(cint(asset.asset_quantity) - sum(held.values()), 0)
	if transaction_type == RECEIPT:
		return 1 if employee and asset.custodian == employee else 0
	return 0 if asset.custodian or asset.status == "Out of Order" else 1


@frappe.whitelist()
def get_asset_details(asset, transaction_type=ISSUE, employee=None):
	"""For the row as soon as an asset is picked: name, location, Available Qty, grouped or not."""
	check_handover_access()
	details = frappe.db.get_value("Asset", asset, ["asset_name", "location", "asset_quantity", "custodian", "status"],
	                              as_dict=True)
	if not details:
		return {}
	return {
		"asset_name": details.asset_name,
		"current_location": details.location,
		"asset_quantity": cint(details.asset_quantity) or 1,
		"grouped": is_grouped(details),
		"available_qty": available_qty(asset, transaction_type, employee, details),
	}


# --- helpers used by the form, the Employee form, the report and the exit alerts ---------
def check_handover_access():
	if not (HANDOVER_ROLES & set(frappe.get_roles())) and frappe.session.user != "Administrator":
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def get_assets_held(employee):
	"""Assets whose Custodian is this employee (what the Full and Final Statement will list), with
	qty 1, plus the grouped assets the employee holds with their quantity (ClickUp 14yr2e58hbm)."""
	assets = frappe.get_all(
		"Asset",
		filters={"custodian": employee, "docstatus": 1, "status": ["not in", CLOSED_ASSET_STATUSES],
		         "asset_quantity": ["<=", 1]},
		fields=["name as asset", "asset_name", "location", "status"],
	)
	for a in assets:
		a.qty = 1
	grouped = frappe.get_all(
		"Asset", filters={"docstatus": 1, "status": ["not in", CLOSED_ASSET_STATUSES], "asset_quantity": [">", 1]},
		fields=["name as asset", "asset_name", "location", "status"],
	)
	held = held_qty([g.asset for g in grouped], employee)
	for g in grouped:
		qty = held.get((g.asset, employee), 0)
		if qty > 0:
			g.qty = qty
			assets.append(g)
	assets.sort(key=lambda a: (a.asset_name or "", a.asset))
	return assets


@frappe.whitelist()
def get_employee_assets(employee):
	check_handover_access()
	return get_assets_held(employee)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def asset_query(doctype, txt, searchfield, start, page_len, filters):
	"""Asset picker: free assets for Issue, the employee's assets for Receipt, each shown with its
	Asset ID, Asset Name and Available Qty (ClickUp 14yr2e58hbm); grouped assets while any quantity
	is available / held. Works for HR users who have no read access on Asset."""
	check_handover_access()
	filters = frappe._dict(filters or {})
	receipt = filters.transaction_type == RECEIPT
	conditions = {"docstatus": 1, "status": ["not in", CLOSED_ASSET_STATUSES]}
	if not receipt:
		conditions["status"] = ["not in", (*CLOSED_ASSET_STATUSES, "Out of Order")]
	if filters.company:
		conditions["company"] = filters.company
	# escape LIKE wildcards so a literal % or _ typed by the user matches itself
	txt = (txt or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	txt = f"%{txt}%"
	assets = frappe.get_all(
		"Asset", filters=conditions,
		or_filters=[["name", "like", txt], ["asset_name", "like", txt], ["item_code", "like", txt]],
		fields=["name", "asset_name", "location", "asset_quantity", "custodian", "status"],
		order_by="asset_name asc, name asc",
	)
	grouped = [a.name for a in assets if is_grouped(a)]
	held = held_qty(grouped) if grouped else {}
	result = []
	for a in assets:
		if is_grouped(a):
			holdings = {emp: q for (name, emp), q in held.items() if name == a.name}
			qty = holdings.get(filters.employee, 0) if receipt else cint(a.asset_quantity) - sum(holdings.values())
		elif receipt:
			qty = 1 if filters.employee and a.custodian == filters.employee else 0
		else:
			qty = 0 if a.custodian else 1
		if qty <= 0:
			continue
		label = _("Held: {0}") if receipt else _("Available: {0}")
		result.append([a.name, a.asset_name, label.format(qty), a.location])
	start, page_len = cint(start), cint(page_len) or 20
	return result[start:start + page_len]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def location_query(doctype, txt, searchfield, start, page_len, filters):
	check_handover_access()
	return frappe.get_all(
		"Location", filters={"name": ["like", f"%{txt}%"]},
		fields=["name"], order_by="name asc",
		limit_start=start, limit_page_length=page_len, as_list=True,
	)

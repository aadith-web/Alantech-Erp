"""Shift Type Work Mode / Early Check-in / Late Checkout / OT Rounding (ClickUp 14yr2e5785z).

Runs once. New fields default to Fixed Shift / Ignore / Ignore / 0, but a shift that already has
Allow Overtime counted every hour beyond the shift length as overtime. Such shifts get Early Checkin
Mode and Late Checkout Mode = OT, so their overtime does not drop to zero after the upgrade.
"""

import frappe

from alantech_erp.setup import shift_ot_fields


def execute():
	shift_ot_fields.execute()  # the fields come from after_migrate, which runs after the patches
	for shift in frappe.get_all("Shift Type", filters={"allow_overtime": 1}, pluck="name"):
		shift_ot_fields.count_outside_shift_as_ot(shift)

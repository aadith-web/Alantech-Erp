"""Alantech yearly holiday lists and shift types.

execute() runs on every migrate (hooks.py after_migrate) and ensure_holiday_lists() runs monthly
(hooks.py scheduler_events). Both only CREATE what is missing, so changes made later in the UI
(shift times, thresholds, overtime, public holidays) are never overwritten.

Holiday lists: one per year, "Alantech Holidays <year>", with every Sunday and the 2nd and 4th
Saturday as Weekly Off. This year's and next year's lists are kept ready; HR adds public holidays
(rows without Weekly Off) to each year's list.

Create a year by hand:
    bench --site <site> execute alantech_erp.setup.shifts.add_year --kwargs "{'year': 2028}"
"""

import calendar
import datetime

import frappe
from frappe.utils import getdate

COMPANY = "Alantech Industries India Pvt Ltd"
HOLIDAY_LIST_PREFIX = "Alantech Holidays"
DEFAULT_SHIFT = "General Shift"

SHIFT_BASE = {
	"enable_auto_attendance": 0,  # attendance comes from Session Log, not HRMS auto attendance
	"allow_overtime": 0,  # overtime only on General Shift, ticked by hand with its Overtime Type
	"enable_late_entry_marking": 1,
	"late_entry_grace_period": 15,
	"enable_early_exit_marking": 1,
	"early_exit_grace_period": 15,
}

# Starting values only: edit them later in Shift Type, they won't be reset.
# HRMS rule: shift length + check-in before + check-out after must stay under 1440 minutes.
SHIFTS = {
	# name: start, end, check-in before (min), check-out after (min), half-day below (h), absent below (h)
	"General Shift": ("09:00:00", "17:00:00", 60, 300, 4, 2),
	"12 Hour Shift": ("09:00:00", "21:00:00", 60, 180, 6, 3),
	# 09:00 to 09:00 next day; stored as 08:59 because HRMS forbids equal start/end and >= 24 h.
	# calculation.py treats it as a full 24 hours.
	"24 Hour Shift": ("09:00:00", "08:59:00", 0, 0, 12, 6),
}


def execute():
	if not frappe.db.exists("Company", COMPANY):
		return  # fresh site before the setup wizard: the next migrate will do it
	ensure_holiday_lists()
	create_shift_types()
	set_default_shift()


# ---------------------------------------------------------------- holiday lists
def holiday_list_name(year):
	return f"{HOLIDAY_LIST_PREFIX} {year}"


def weekly_offs(year):
	"""Every Sunday plus the 2nd and 4th Saturday of each month."""
	rows = []
	for month in range(1, 13):
		saturdays = 0
		for day in range(1, calendar.monthrange(year, month)[1] + 1):
			date = datetime.date(year, month, day)
			if date.weekday() == 6:
				rows.append({"holiday_date": date, "description": "Sunday", "weekly_off": 1})
			elif date.weekday() == 5:
				saturdays += 1
				if saturdays in (2, 4):
					label = "Second Saturday" if saturdays == 2 else "Fourth Saturday"
					rows.append({"holiday_date": date, "description": label, "weekly_off": 1})
	return rows


def create_year(year):
	"""Create 'Alantech Holidays <year>' if it doesn't exist. Returns its name."""
	name = holiday_list_name(year)
	if frappe.db.exists("Holiday List", name):
		return name
	frappe.get_doc(
		{
			"doctype": "Holiday List",
			"holiday_list_name": name,
			"from_date": f"{year}-01-01",
			"to_date": f"{year}-12-31",
			"holidays": weekly_offs(year),
		}
	).insert(ignore_permissions=True)
	return name


def ensure_holiday_lists():
	"""This year's and next year's lists, so next year's exists well before January."""
	if not frappe.db.exists("Company", COMPANY):
		return
	this_year = datetime.date.today().year
	for year in (this_year, this_year + 1):
		create_year(year)
	if not frappe.db.get_value("Company", COMPANY, "default_holiday_list"):
		frappe.db.set_value("Company", COMPANY, "default_holiday_list", holiday_list_name(this_year))


def add_year(year):
	"""Manual: bench --site <site> execute alantech_erp.setup.shifts.add_year --kwargs "{'year': 2028}" """
	name = create_year(int(year))
	frappe.db.commit()
	print(f"{name} ready")


# ---------------------------------------------------------------- shift types
def create_shift_types():
	meta = frappe.get_meta("Shift Type")
	for name, (start, end, before, after, half, absent) in SHIFTS.items():
		if frappe.db.exists("Shift Type", name):
			continue
		values = {
			**SHIFT_BASE,
			"start_time": start,
			"end_time": end,
			"begin_check_in_before_shift_start_time": before,
			"allow_check_out_after_shift_end_time": after,
			"working_hours_threshold_for_half_day": half,
			"working_hours_threshold_for_absent": absent,
		}
		values = {k: v for k, v in values.items() if meta.has_field(k)}
		frappe.get_doc({"doctype": "Shift Type", "name": name, "__newname": name, **values}).insert(
			ignore_permissions=True
		)

def set_default_shift():
	"""New employees get General Shift unless HR picks another. Create-only, like the shifts."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if not frappe.db.exists("Shift Type", DEFAULT_SHIFT):
		return
	if frappe.db.exists(
		"Property Setter", {"doc_type": "Employee", "field_name": "default_shift", "property": "default"}
	):
		return  # already set (or changed by HR in Customize Form): leave it
	make_property_setter(
		"Employee", "default_shift", "default", DEFAULT_SHIFT, "Text", validate_fields_for_doctype=False
	)


def fill_missing_shifts():
	"""One-off for existing active employees without a shift."""
	frappe.db.set_value(
		"Employee", {"status": "Active", "default_shift": ["is", "not set"]}, "default_shift", DEFAULT_SHIFT
	)
	frappe.db.commit()
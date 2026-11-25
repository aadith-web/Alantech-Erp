# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Shift Type: overnight and 24-hour shifts can be saved (ClickUp 14yr2e58jzh, production issue).

HRMS (ShiftType.validate) refuses an End Time equal to the Start Time, and a shift whose length plus
"Begin check-in before shift start time" + "Allow check-out after shift end time" (60 minutes each by
default) reaches 24 hours ("Please reduce Allow check-out after shift end time ..."). Those two fields
are in the Auto Attendance Settings section, hidden while Enable Auto Attendance is off (always off:
the app's Session Log makes the attendance), so HR could not save a 24 Hour Shift.

before_validate (runs before HRMS's checks):
- End Time earlier than Start Time = ends the next day (HRMS already does this; now said on the form).
- End Time = Start Time = a 24-hour shift: stored as Start Time - 1 minute (09:00 -> 08:59 next day),
  the way the app's own "24 Hour Shift" is set up; the Session Log calculation counts it as 24 hours.
- Shift length + the two buffers reaching 24 hours: the buffers are reduced so they fit (for a
  24-hour shift both become 0), with a message saying so.
execute() (after_migrate): the End Time description tells HR about next-day and 24-hour shifts.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint, get_time

DAY_MINUTES = 24 * 60
BEFORE = "begin_check_in_before_shift_start_time"
AFTER = "allow_check_out_after_shift_end_time"
END_TIME_NOTE = (
	"An End Time earlier than the Start Time ends the next day (e.g. 21:00 to 06:00). "
	"The same time as the Start Time is a 24-hour shift (e.g. 09:00 to 09:00 next day)."
)


def execute():
	make_property_setter("Shift Type", "end_time", "description", END_TIME_NOTE, "Small Text",
		validate_fields_for_doctype=False)


def shift_minutes(start, end):
	"""Length of the shift in minutes; an end at or before the start is the next day."""
	start, end = get_time(start), get_time(end)
	day = datetime(2000, 1, 1)
	begin, finish = datetime.combine(day, start), datetime.combine(day, end)
	if finish <= begin:
		finish += timedelta(days=1)
	return round((finish - begin).total_seconds() / 60)


def fit_buffers(length, before, after):
	"""(before, after) reduced so length + before + after stays under 24 hours (after first)."""
	room = max(DAY_MINUTES - 1 - length, 0)
	before, after = max(cint(before), 0), max(cint(after), 0)
	if before + after <= room:
		return before, after
	after = max(room - before, 0)
	before = min(before, room)
	return before, after


def before_validate(doc, method=None):
	if not doc.start_time or not doc.end_time:
		return
	start, end = get_time(doc.start_time), get_time(doc.end_time)
	notes = []
	if start == end:
		doc.end_time = (datetime.combine(datetime(2000, 1, 1), start) - timedelta(minutes=1)).time().strftime("%H:%M:%S")
		notes.append(_("End Time = Start Time: saved as a 24-hour shift, {0} to {1} the next day.").format(
			start.strftime("%H:%M"), get_time(doc.end_time).strftime("%H:%M")))

	length = shift_minutes(doc.start_time, doc.end_time)
	before, after = fit_buffers(length, doc.get(BEFORE), doc.get(AFTER))
	if (before, after) != (cint(doc.get(BEFORE)), cint(doc.get(AFTER))):
		doc.set(BEFORE, before)
		doc.set(AFTER, after)
		notes.append(_("Check-in before start / check-out after end set to {0} / {1} minutes so the shift "
			"does not overlap the next one.").format(before, after))
	if notes:
		frappe.msgprint("<br>".join(notes), title=_("Shift Times"), indicator="blue", alert=True)

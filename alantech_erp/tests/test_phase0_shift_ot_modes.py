# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Shift Type Work Mode, Early Check-in / Late Checkout handling and OT rounding.

ClickUp: https://app.clickup.com/t/14yr2e5785z
Code:    alantech_erp/setup/shift_ot_fields.py, session_log/calculation.py get_overtime_hours

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_shift_ot_modes

The calculation tests use an 09:00-17:00 shift in memory. The end-to-end tests create the
"TEST-P10 *" Shift Types and TEST-P10- employees and remove them again in tearDownClass.
"""

import frappe
from frappe.utils import add_days, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.alantech.doctype.session_log.calculation import (
	calculate,
	get_day_type,
	get_overtime_hours,
	get_shift_window,
	round_down_hours,
	set_overtime,
)
from alantech_erp.setup.shift_ot_fields import DEFAULTS, FIXED, FLEXIBLE, IGNORE, OT
from alantech_erp.setup.shifts import OVERTIME_TYPE
from alantech_erp.tests.test_phase0_employee_user import COMPANY, employee_doc

DAY = "2026-10-14"
SHIFT_PREFIX = "TEST-P10"
FIELDS = ("work_mode", "regular_hours_per_day", "early_checkin_mode", "late_checkout_mode", "round_ot_minutes_to")


def shift(**values):
	"""09:00-17:00 with overtime on; values override the OT handling."""
	return frappe._dict(
		{
			"name": "Test Shift", "start_time": "09:00:00", "end_time": "17:00:00",
			"begin_check_in_before_shift_start_time": 120, "allow_check_out_after_shift_end_time": 300,
			"allow_overtime": 1, "overtime_type": "Test OT", **DEFAULTS, **values,
		}
	)


def rule(maximum=0):
	return frappe._dict(name="Test OT", applicable_for_weekend=1, applicable_for_public_holiday=1,
		maximum_overtime_hours_allowed=maximum)


def ot(shift_doc, first_in, last_out, day_type="Working Day", maximum=0):
	"""Overtime hours for one day's first IN and last OUT ("HH:MM", same day)."""
	first_in, last_out = f"{DAY} {first_in}:00", f"{DAY} {last_out}:00"
	doc = frappe._dict(first_in=first_in, last_out=last_out, day_type=day_type,
		working_hours=frappe.utils.time_diff_in_hours(last_out, first_in))
	return get_overtime_hours(doc, rule(maximum), get_shift_window(DAY, shift_doc), shift_doc)


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P10-%"]}, pluck="name")
	if employees:  # the OUT punches build Session Logs (+ Attendance / Overtime Log)
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		for doctype in ("Employee Checkin", "Attendance", "Overtime Log"):
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	for name in frappe.get_all("Shift Type", filters={"name": ["like", f"{SHIFT_PREFIX}%"]}, pluck="name"):
		frappe.delete_doc("Shift Type", name, force=1, ignore_permissions=True)
	frappe.db.commit()


class TestPhase0ShiftOtModes(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cleanup()

	@classmethod
	def tearDownClass(cls):
		cleanup()
		super().tearDownClass()

	# ---------------------------------------------------------------- fields
	def test_01_fields_on_shift_type(self):
		meta = frappe.get_meta("Shift Type")
		for fieldname in FIELDS:
			self.assertTrue(meta.get_field(fieldname), f"{fieldname} missing")
			self.assertTrue(meta.get_field(fieldname).description, f"{fieldname} has no description")
		regular = meta.get_field("regular_hours_per_day")
		self.assertEqual((regular.depends_on, regular.mandatory_depends_on),
			(f"eval:doc.work_mode == '{FLEXIBLE}'",) * 2)
		for fieldname in ("early_checkin_mode", "late_checkout_mode"):
			self.assertEqual(meta.get_field(fieldname).depends_on, f"eval:doc.work_mode != '{FLEXIBLE}'")
			self.assertEqual(meta.get_field(fieldname).options.split("\n"), [IGNORE, OT])
		self.assertEqual(meta.get_field("round_ot_minutes_to").options.split("\n"), ["0", "15", "30", "60"])
		# placed after the Overtime section
		order = [f.fieldname for f in meta.fields]
		self.assertLess(order.index("overtime_type"), order.index("work_mode"))

	def test_02_existing_shifts_defaulted_after_migrate(self):
		for name, row in {r.name: r for r in frappe.get_all("Shift Type", fields=["name", "allow_overtime", *FIELDS])}.items():
			if name.startswith(SHIFT_PREFIX):
				continue
			self.assertEqual(row.work_mode, FIXED, name)
			self.assertEqual(row.round_ot_minutes_to, "0", name)
			# a shift that already had overtime keeps counting time outside the shift (no behaviour change)
			expected = OT if row.allow_overtime else IGNORE
			self.assertEqual((row.early_checkin_mode, row.late_checkout_mode), (expected, expected), name)

	def test_03_flexible_needs_regular_hours(self):
		doc = frappe.get_doc({"doctype": "Shift Type", "name": f"{SHIFT_PREFIX} Flexible",
			"__newname": f"{SHIFT_PREFIX} Flexible", "start_time": "09:00:00", "end_time": "17:00:00",
			"work_mode": FLEXIBLE, "regular_hours_per_day": 0})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)
		doc.regular_hours_per_day = 8
		doc.insert(ignore_permissions=True)
		doc.reload()
		self.assertEqual([doc.get(f) for f in FIELDS], [FLEXIBLE, 8, IGNORE, IGNORE, "0"])

	def test_04_new_shift_gets_defaults(self):
		doc = frappe.get_doc({"doctype": "Shift Type", "name": f"{SHIFT_PREFIX} Default",
			"__newname": f"{SHIFT_PREFIX} Default", "start_time": "09:00:00", "end_time": "17:00:00"})
		doc.insert(ignore_permissions=True)
		doc.reload()
		self.assertEqual([doc.get(f) for f in FIELDS], [FIXED, 0, IGNORE, IGNORE, "0"])

	# ---------------------------------------------------------------- Fixed Shift
	def test_05_early_checkin(self):
		self.assertEqual(ot(shift(early_checkin_mode=IGNORE), "07:30", "17:00"), 0)
		self.assertEqual(ot(shift(early_checkin_mode=OT), "07:30", "17:00"), 1.5)

	def test_06_late_checkout(self):
		self.assertEqual(ot(shift(late_checkout_mode=IGNORE), "09:00", "19:15"), 0)
		self.assertEqual(ot(shift(late_checkout_mode=OT), "09:00", "19:15"), 2.25)

	def test_07_early_and_late_are_separate(self):
		both = shift(early_checkin_mode=OT, late_checkout_mode=OT)
		self.assertEqual(ot(both, "08:00", "18:00"), 2)
		self.assertEqual(ot(shift(late_checkout_mode=OT), "08:00", "18:00"), 1, "early hour ignored")
		self.assertEqual(ot(both, "10:00", "18:00"), 1, "late arrival does not cancel late checkout OT")
		self.assertEqual(ot(both, "09:00", "17:00"), 0)

	# ---------------------------------------------------------------- Flexible Threshold
	def test_08_flexible_threshold(self):
		flexible = shift(work_mode=FLEXIBLE, regular_hours_per_day=8, early_checkin_mode=OT, late_checkout_mode=OT)
		self.assertEqual(ot(flexible, "11:00", "21:30"), 2.5, "shift start/end not used")
		self.assertEqual(ot(flexible, "06:00", "13:00"), 0, "below the regular hours")
		self.assertEqual(ot(shift(work_mode=FLEXIBLE, regular_hours_per_day=6), "11:00", "21:30"), 4.5)

	# ---------------------------------------------------------------- rounding
	def test_09_rounding_down(self):
		# 52 minutes of late checkout OT
		for step, expected in (("0", 0.87), ("15", 0.75), ("30", 0.5), ("60", 0)):
			self.assertEqual(ot(shift(late_checkout_mode=OT, round_ot_minutes_to=step), "09:00", "17:52"),
				expected, f"rounding {step}")
		self.assertEqual(round_down_hours(1.1, 30), 1.0)
		self.assertEqual(round_down_hours(1.5, 30), 1.5, "exact multiple kept")
		self.assertEqual(round_down_hours(0.1, 0), 0.1)

	def test_10_rounding_after_maximum(self):
		late = shift(late_checkout_mode=OT, round_ot_minutes_to="60")
		self.assertEqual(ot(late, "09:00", "21:00", maximum=2.5), 2, "capped to 2.5, then rounded to 2")

	def test_11_off_days_still_count_all_hours(self):
		self.assertEqual(ot(shift(), "10:00", "14:00", day_type="Weekly Off"), 4)
		self.assertEqual(ot(shift(round_ot_minutes_to="60"), "10:00", "14:50", day_type="Holiday"), 4)

	def test_12_two_shifts_same_punches_different_ot(self):
		punches = ("07:00", "19:40")
		results = {
			"fixed, both OT, 30 min": ot(shift(early_checkin_mode=OT, late_checkout_mode=OT, round_ot_minutes_to="30"), *punches),
			"fixed, late only": ot(shift(late_checkout_mode=OT), *punches),
			"flexible 10 h": ot(shift(work_mode=FLEXIBLE, regular_hours_per_day=10), *punches),
		}
		self.assertEqual(results, {"fixed, both OT, 30 min": 4.5, "fixed, late only": 2.67, "flexible 10 h": 2.67})
		self.assertNotEqual(results["fixed, both OT, 30 min"], results["fixed, late only"])

	def test_13_no_ot_when_overtime_disabled(self):
		off = shift(allow_overtime=0, early_checkin_mode=OT, late_checkout_mode=OT)
		doc = frappe._dict(first_in=f"{DAY} 07:00:00", last_out=f"{DAY} 20:00:00", working_hours=13,
			day_type="Working Day")
		set_overtime(doc, off, get_shift_window(DAY, off))
		self.assertEqual((doc.overtime_rule, doc.overtime_hours), (None, 0))

	# ---------------------------------------------------------------- end to end
	def test_14_session_log_reads_the_employees_shift(self):
		"""Same check-ins, two employees on different shifts: different overtime on the Session Log."""
		if not frappe.db.exists("Overtime Type", OVERTIME_TYPE):
			self.skipTest(f"Overtime Type {OVERTIME_TYPE} missing")
		base = getdate(today())
		day = add_days(base, -base.weekday() - 77 + 2)  # a Wednesday 11 weeks back
		shifts = {
			"Late OT": {"late_checkout_mode": OT, "round_ot_minutes_to": "30"},
			"Flexible 9h": {"work_mode": FLEXIBLE, "regular_hours_per_day": 9},
			"No OT": {"allow_overtime": 0, "late_checkout_mode": OT},
		}
		expected = {"Late OT": 2.5, "Flexible 9h": 2, "No OT": 0}
		for i, (label, values) in enumerate(shifts.items(), start=1):
			name = f"{SHIFT_PREFIX} {label}"
			frappe.get_doc({"doctype": "Shift Type", "name": name, "__newname": name, "start_time": "09:00:00",
				"end_time": "17:00:00", "begin_check_in_before_shift_start_time": 60,
				"allow_check_out_after_shift_end_time": 300, "allow_overtime": 1, "overtime_type": OVERTIME_TYPE,
				**values}).insert(ignore_permissions=True)
			emp = employee_doc(f"P10 Emp{i}", f"TEST-P10-EMP{i}", None, default_shift=name)
			emp.insert(ignore_permissions=True)
			for time, log_type in (("08:45", "IN"), ("19:45", "OUT")):
				frappe.get_doc({"doctype": "Employee Checkin", "employee": emp.name, "time": f"{day} {time}:00",
					"log_type": log_type}).insert(ignore_permissions=True)
			if get_day_type(emp.name, day, frappe.get_cached_doc("Shift Type", name)) != "Working Day":
				self.skipTest(f"{day} is not a working day")
			log = frappe.get_doc({"doctype": "Session Log", "employee": emp.name, "company": COMPANY, "log_date": day})
			calculate(log)  # in memory: no Attendance / Overtime Log
			self.assertEqual((log.shift, log.working_hours), (name, 11.0))
			self.assertEqual(log.overtime_hours, expected[label], label)

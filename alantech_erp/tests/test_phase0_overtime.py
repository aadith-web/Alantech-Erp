# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 4: overtime (Overtime Type, Overtime Log, approval).

ClickUp: https://app.clickup.com/t/14yr2e56c9w

Overtime only on General Shift (Allow Overtime + Overtime Type); none on 12 Hour / 24 Hour shifts.
A check-out builds the Session Log; hours beyond the shift give an Overtime Log at
    rate = (gross - fixed allowances) / days in month / 8 x 1.5
Every user holds only their matrix roles; the check-ins are punched by the HR User and every
permission check runs as the user under test.

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_overtime

test_01 checks the site's own overtime configuration. The other tests set up the configuration
the task asks for (Overtime Settings, General Shift overtime, a salary structure for emp1) and put
the site's values back afterwards. Everything created here uses p4.*@example.com addresses, the
TEST-P4- employee numbers and TEST-P4 masters, and is removed again in tearDownClass.
"""

import frappe
from frappe.utils import add_days, flt, get_first_day, get_last_day, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.alantech.doctype.session_log_settings.session_log_settings import TRIGGER_ON_CHECKOUT
from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT, holiday_list_name
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, COMPANY, employee_doc, make_user
from alantech_erp.tests.test_phase0_session_log import (
	SETTINGS_FIELDS,
	attendance_count,
	checkin,
	get_log,
	set_settings,
)

HR_MANAGER = "p4.hr.manager@example.com"
HR_USER = "p4.hr.user@example.com"
APPROVER = "p4.approver@example.com"
EMP1 = "p4.emp1@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

NO_OVERTIME_SHIFTS = ("12 Hour Shift", "24 Hour Shift")
TRANSACTIONS = ("Employee Checkin", "Attendance", "Overtime Log", "Salary Structure Assignment")

OT_TYPE = "TEST-P4 Overtime"
OT_COMPONENT = "TEST-P4 Overtime"
HOLIDAY_OT_COMPONENT = "TEST-P4 Holiday Overtime"
FIXED_ALLOWANCE = "TEST-P4 Fixed Allowance"
STRUCTURE = "TEST-P4 Structure"

# emp1's monthly salary: gross 45000, of which 3000 is a fixed allowance (not applicable for OT)
EARNINGS = {"Basic": 30000, "House Rent Allowance": 12000, FIXED_ALLOWANCE: 3000}
APPLICABLE = ("Basic", "House Rent Allowance")
OT_BASE = 42000  # gross - fixed allowances
HOURS_PER_DAY = 8
NORMAL_MULTIPLIER = 1.5
HOLIDAY_MULTIPLIER = 2.0


def ot_rate(day, multiplier=NORMAL_MULTIPLIER):
	"""(gross - fixed allowances) / days in month / 8 x multiplier"""
	return flt(OT_BASE / getdate(get_last_day(day)).day / HOURS_PER_DAY * multiplier, 2)


# ---------------------------------------------------------------- masters
def make_component(name, abbr):
	if not frappe.db.exists("Salary Component", name):
		frappe.get_doc({"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": abbr,
			"type": "Earning", "depends_on_payment_days": 0}).insert(ignore_permissions=True)


def make_masters():
	make_component(FIXED_ALLOWANCE, "TP4FA")
	make_component(OT_COMPONENT, "TP4OT")
	make_component(HOLIDAY_OT_COMPONENT, "TP4HOT")
	if not frappe.db.exists("Overtime Type", OT_TYPE):
		ot_type = frappe.new_doc("Overtime Type")
		ot_type.update({"overtime_salary_component": OT_COMPONENT, "overtime_calculation_method": "Fixed Hourly Rate",
			"standard_multiplier": NORMAL_MULTIPLIER, "applicable_for_weekend": 1,
			"applicable_for_public_holiday": 1})
		ot_type.insert(ignore_permissions=True, set_name=OT_TYPE)
	if not frappe.db.exists("Salary Structure", STRUCTURE):
		structure = frappe.new_doc("Salary Structure")
		structure.update({"company": COMPANY, "is_active": "Yes", "payroll_frequency": "Monthly",
			"currency": frappe.db.get_value("Company", COMPANY, "default_currency")})
		for component, amount in EARNINGS.items():
			structure.append("earnings", {"salary_component": component, "amount": amount,
				"abbr": frappe.db.get_value("Salary Component", component, "salary_component_abbr")})
		structure.insert(ignore_permissions=True, set_name=STRUCTURE)
		structure.submit()


def assign_structure(employee, from_date):
	frappe.get_doc({"doctype": "Salary Structure Assignment", "employee": employee, "salary_structure": STRUCTURE,
		"company": COMPANY, "currency": frappe.db.get_value("Company", COMPANY, "default_currency"),
		"from_date": from_date, "base": sum(EARNINGS.values()),
		"payroll_payable_account": frappe.db.get_value("Company", COMPANY, "default_payroll_payable_account"),
	}).insert(ignore_permissions=True).submit()


# ---------------------------------------------------------------- site configuration
def snapshot_overtime():
	return {
		"settings": frappe.get_doc("Overtime Settings").as_dict(),
		"shifts": {name: frappe.db.get_value("Shift Type", name, ["allow_overtime", "overtime_type"], as_dict=True)
			for name in (DEFAULT_SHIFT, *NO_OVERTIME_SHIFTS)},
	}


def restore_overtime(snapshot):
	"""Straight to the DB: the site's own values may not pass validation (e.g. 0 hours per day)."""
	settings = snapshot["settings"]
	for field in ("enable_multiple_ot", "base_component_method", "working_days_base", "working_hours_per_day"):
		frappe.db.set_single_value("Overtime Settings", field, settings.get(field))
	for table, doctype in (("overtime_type_rules", "Overtime Type Rule"),
			("applicable_overtime_component", "Overtime Applicable Component")):
		frappe.db.delete(doctype, {"parent": "Overtime Settings", "parentfield": table})
		for row in settings.get(table):
			frappe.get_doc(row).db_insert()
	frappe.clear_document_cache("Overtime Settings", "Overtime Settings")
	for name, values in snapshot["shifts"].items():
		set_shift_overtime(name, values.allow_overtime, values.overtime_type)


def set_shift_overtime(shift, allow, overtime_type):
	frappe.db.set_value("Shift Type", shift, {"allow_overtime": allow, "overtime_type": overtime_type})
	frappe.clear_document_cache("Shift Type", shift)


def set_overtime_settings(multiple_ot=0):
	"""Working hours per day 8, Month Days, applicable components, Normal rule Salary Derived x 1.5
	(and the Holiday rule x 2 when multiple OT is on)."""
	settings = frappe.get_doc("Overtime Settings")
	settings.update({"enable_multiple_ot": multiple_ot, "base_component_method": "Custom",
		"working_days_base": "Month Days", "working_hours_per_day": HOURS_PER_DAY})
	settings.set("applicable_overtime_component", [{"salary_component": c} for c in APPLICABLE])
	settings.set("overtime_type_rules", [
		{"ot_type": "Normal", "salary_component": OT_COMPONENT, "calculation_method": "Salary Derived",
			"component_method": "Component Wise", "rate_multiplier": NORMAL_MULTIPLIER},
		{"ot_type": "Holiday", "salary_component": HOLIDAY_OT_COMPONENT, "calculation_method": "Salary Derived",
			"component_method": "Component Wise", "rate_multiplier": HOLIDAY_MULTIPLIER},
	])
	settings.save(ignore_permissions=True)


# ---------------------------------------------------------------- cleanup / helpers
def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P4-%"]}, pluck="name")
	if employees:
		session_logs = frappe.get_all("Session Log", filters={"employee": ["in", employees]}, pluck="name")
		if session_logs:
			frappe.db.delete("Attendance Log Checkin", {"parent": ["in", session_logs]})
			frappe.db.delete("Session Log", {"name": ["in", session_logs]})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p4.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	if frappe.db.exists("Salary Structure", STRUCTURE):
		frappe.db.delete("Salary Detail", {"parent": STRUCTURE, "parenttype": "Salary Structure"})
		frappe.db.delete("Salary Structure", {"name": STRUCTURE})
	frappe.db.delete("Overtime Salary Component", {"parent": OT_TYPE})
	frappe.db.delete("Overtime Type", {"name": OT_TYPE})
	for component in (FIXED_ALLOWANCE, OT_COMPONENT, HOLIDAY_OT_COMPONENT):
		frappe.db.delete("Salary Component Account", {"parent": component})
		frappe.db.delete("Salary Component", {"name": component})
	frappe.db.commit()


def day_type(day):
	weekly_off = frappe.db.get_value(
		"Holiday", {"parent": holiday_list_name(getdate(day).year), "holiday_date": day}, "weekly_off"
	)
	if weekly_off is None:
		return "Working Day"
	return "Weekly Off" if weekly_off else "Holiday"


def past_days(of_type, weekday, count):
	"""The latest `count` past dates on `weekday` (0 = Monday) of the given day type, from 3 weeks back."""
	base = getdate(today())
	day = add_days(base, -((base.weekday() - weekday) % 7) - 21)
	days = []
	while len(days) < count:
		if day_type(day) == of_type:
			days.append(day)
		day = add_days(day, -7)
	return days


def punch(employee, time_in, time_out):
	"""IN and OUT; the OUT builds the Session Log ("On Check-out")."""
	checkin(employee, f"{time_in}:00", "IN").insert()
	checkin(employee, f"{time_out}:00", "OUT").insert()


def overtime_logs(employee, day):
	return frappe.get_all("Overtime Log", filters={"employee": employee, "overtime_date": day, "docstatus": ["!=", 2]},
		pluck="name")


class TestPhase0Overtime(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		cls.site_overtime = snapshot_overtime()
		session_settings = frappe.get_doc("Session Log Settings")
		cls.original_settings = {f: session_settings.get(f) for f in SETTINGS_FIELDS}
		set_settings(require_log_approval=0, log_creation_trigger=TRIGGER_ON_CHECKOUT, approver_role="HR Manager",
			hold_missing_checkout=1, auto_submit_attendance=1, auto_submit_overtime=1, lock_after_processing=1)

		make_masters()
		set_overtime_settings()
		set_shift_overtime(DEFAULT_SHIFT, 1, OT_TYPE)
		for shift in NO_OVERTIME_SHIFTS:
			set_shift_overtime(shift, 0, None)

		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			make_user(email, roles)
			emp = employee_doc(f"P4 User{i}", f"TEST-P4-USER{i}", None, user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)

		# emp1: General Shift, salary structure, a user restricted to their own record
		emp1 = employee_doc("P4 Emp1", "TEST-P4-EMP1", None, reports_to=cls.employee_of[APPROVER],
			default_shift=DEFAULT_SHIFT)
		emp1.insert(ignore_permissions=True)
		create_user(emp1.name, email=EMP1, create_user_permission=1)
		cls.emp1 = emp1.name
		# test days: past Mondays (working days) and Sundays (weekly off); salary from their first month
		mondays = past_days("Working Day", 0, 4)
		cls.ot_day, cls.draft_ot_day, cls.manual_ot_day, cls.no_ot_day = mondays
		cls.sundays = past_days("Weekly Off", 6, 2)
		salary_from = get_first_day(min(mondays + cls.sundays))
		assign_structure(cls.emp1, salary_from)
		# one employee on each shift without overtime
		cls.no_ot_employee = {}
		for i, shift in enumerate(NO_OVERTIME_SHIFTS, start=2):
			emp = employee_doc(f"P4 Emp{i}", f"TEST-P4-EMP{i}", None, reports_to=cls.employee_of[APPROVER],
				default_shift=shift)
			emp.insert(ignore_permissions=True)
			assign_structure(emp.name, salary_from)
			cls.no_ot_employee[shift] = emp.name
		frappe.clear_cache(user=EMP1)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		restore_overtime(cls.site_overtime)
		set_settings(**cls.original_settings)
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def assert_overtime_log(self, day, hours, ot_type, rate):
		log = get_log(self.emp1, day)
		self.assertIsNotNone(log, f"no Session Log for {day}")
		self.assertIsNone(log.error_log, log.error_log)
		self.assertEqual(log.overtime_rule, OT_TYPE)
		self.assertEqual(log.overtime_hours, hours)
		self.assertTrue(log.overtime, f"{day}: no Overtime Log linked")
		ot = frappe.get_doc("Overtime Log", log.overtime)
		self.assertEqual((ot.employee, getdate(ot.overtime_date), ot.attendance_log), (self.emp1, day, log.name))
		self.assertEqual((ot.ot_type, ot.overtime_hours, ot.overtime_rate), (ot_type, hours, rate))
		self.assertEqual(ot.overtime_amount, flt(hours * rate, 2))
		self.assertEqual(overtime_logs(self.emp1, day), [ot.name], "duplicate Overtime Log")
		return log, ot

	# ---------------------------------------------------------------- site configuration
	def test_01_site_overtime_configuration(self):
		"""The site's own setup (before this test changed it), as the task asks."""
		settings = self.site_overtime["settings"]
		problems = []
		if flt(settings.working_hours_per_day) != HOURS_PER_DAY:
			problems.append(f"Working Hours Per Day is {settings.working_hours_per_day}, not 8")
		if settings.working_days_base != "Month Days":
			problems.append(f"Working Days Base is {settings.working_days_base}, not Month Days")
		if not settings.applicable_overtime_component:
			problems.append("no Applicable Overtime Components")
		rules = {r.ot_type: r for r in settings.overtime_type_rules}
		wanted = ("Normal", "Holiday") if settings.enable_multiple_ot else ("Normal",)
		for ot_type in wanted:
			rule = rules.get(ot_type)
			if not rule:
				problems.append(f"no {ot_type} rule")
			elif rule.calculation_method != "Salary Derived" or flt(rule.rate_multiplier) != NORMAL_MULTIPLIER:
				problems.append(f"{ot_type} rule is {rule.calculation_method} x {rule.rate_multiplier}")
		shifts = self.site_overtime["shifts"]
		if not (shifts[DEFAULT_SHIFT].allow_overtime and shifts[DEFAULT_SHIFT].overtime_type):
			problems.append(f"{DEFAULT_SHIFT}: Allow Overtime / Overtime Type not set")
		for shift in NO_OVERTIME_SHIFTS:
			if shifts[shift].allow_overtime:
				problems.append(f"{shift} allows overtime")
		self.assertEqual(problems, [], "site overtime configuration")

	def test_02_users_have_exactly_their_roles(self):
		for email, expected in {**TEST_USERS, EMP1: {"Employee"}}.items():
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")

	# ---------------------------------------------------------------- overtime day
	def test_03_overtime_day_creates_overtime_log(self):
		"""09:00-19:00 on General Shift (09:00-17:00): 2 h overtime at the Normal rate."""
		frappe.set_user(HR_USER)
		punch(self.emp1, f"{self.ot_day} 09:00", f"{self.ot_day} 19:00")
		frappe.set_user("Administrator")
		log, ot = self.assert_overtime_log(self.ot_day, 2.0, "Normal", ot_rate(self.ot_day))
		self.assertEqual(log.working_hours, 10.0)
		self.assertEqual(log.status, "Processed")
		self.assertEqual(ot.docstatus, 1, "Overtime Log not submitted (Auto Submit Overtime is on)")
		self.assertEqual(attendance_count(self.emp1, self.ot_day), 1)

	def test_04_rate_formula(self):
		"""(gross - fixed allowances) / days in month / 8 x 1.5, e.g. 42000 / 30 / 8 x 1.5 = 262.5"""
		from alantech_erp.alantech.doctype.session_log.processing import get_overtime_rate

		self.assertEqual(ot_rate(getdate("2026-11-15")), 262.5)
		log = frappe._dict(employee=self.emp1, log_date=self.ot_day)
		self.assertEqual(get_overtime_rate(log, "Normal"), ot_rate(self.ot_day))
		self.assertEqual(get_overtime_rate(log, "Holiday"), ot_rate(self.ot_day), "multiple OT off: Normal rule")

	def test_05_no_overtime_within_shift(self):
		frappe.set_user(HR_USER)
		punch(self.emp1, f"{self.no_ot_day} 09:00", f"{self.no_ot_day} 17:00")
		frappe.set_user("Administrator")
		log = get_log(self.emp1, self.no_ot_day)
		self.assertEqual((log.overtime_rule, log.overtime_hours, log.overtime), (OT_TYPE, 0, None))
		self.assertEqual(overtime_logs(self.emp1, self.no_ot_day), [])

	def test_06_weekly_off_overtime(self):
		"""Weekly off: all worked hours are overtime, OT type Holiday. Multiple OT off -> Normal rule's
		rate; on -> the Holiday rule's rate."""
		first, second = self.sundays
		frappe.set_user(HR_USER)
		punch(self.emp1, f"{first} 10:00", f"{first} 14:00")
		frappe.set_user("Administrator")
		self.assert_overtime_log(first, 4.0, "Holiday", ot_rate(first))

		set_overtime_settings(multiple_ot=1)
		try:
			frappe.set_user(HR_USER)
			punch(self.emp1, f"{second} 10:00", f"{second} 14:00")
		finally:
			frappe.set_user("Administrator")
			set_overtime_settings(multiple_ot=0)
		self.assert_overtime_log(second, 4.0, "Holiday", ot_rate(second, HOLIDAY_MULTIPLIER))

	# ---------------------------------------------------------------- no overtime on 12 / 24 hour shifts
	def test_07_no_overtime_on_12_and_24_hour_shifts(self):
		day = self.ot_day
		punches = {
			"12 Hour Shift": (f"{day} 08:00", f"{day} 22:30"),  # 14.5 h on a 12 h shift
			"24 Hour Shift": (f"{day} 09:00", f"{add_days(day, 1)} 08:30"),  # 23.5 h
		}
		frappe.set_user(HR_USER)
		for shift, (time_in, time_out) in punches.items():
			punch(self.no_ot_employee[shift], time_in, time_out)
		frappe.set_user("Administrator")
		for shift, employee in self.no_ot_employee.items():
			log = get_log(employee, day)
			self.assertIsNotNone(log, f"{shift}: no Session Log")
			self.assertEqual(log.shift, shift)
			self.assertGreater(log.working_hours, 12, f"{shift}: punches not counted")
			self.assertEqual((log.overtime_rule, log.overtime_hours, log.overtime), (None, 0, None), shift)
			self.assertEqual(overtime_logs(employee, day), [], f"{shift}: Overtime Log created")

	# ---------------------------------------------------------------- HR User / HR Manager
	def test_08_hr_user_creates_and_edits_overtime_log(self):
		frappe.set_user(HR_USER)
		ot = frappe.get_doc({"doctype": "Overtime Log", "employee": self.emp1, "overtime_date": self.manual_ot_day,
			"ot_type": "Normal", "overtime_hours": 1, "overtime_rate": ot_rate(self.manual_ot_day)}).insert()
		self.assertEqual(ot.overtime_amount, ot_rate(self.manual_ot_day))
		ot.overtime_hours = 3
		ot.save()
		self.assertEqual(ot.overtime_amount, flt(3 * ot_rate(self.manual_ot_day), 2))
		self.assertEqual((ot.owner, ot.modified_by), (HR_USER, HR_USER))
		with self.assertRaises(frappe.PermissionError, msg="HR User could submit"):
			frappe.get_doc("Overtime Log", ot.name).submit()

		frappe.set_user(HR_MANAGER)
		ot = frappe.get_doc("Overtime Log", ot.name)
		ot.submit()
		self.assertEqual(frappe.db.get_value("Overtime Log", ot.name, "docstatus"), 1)

	def test_09_hr_manager_submits_draft_overtime_from_session_log(self):
		set_settings(auto_submit_overtime=0)
		try:
			frappe.set_user(HR_USER)
			punch(self.emp1, f"{self.draft_ot_day} 09:00", f"{self.draft_ot_day} 18:30")
		finally:
			frappe.set_user("Administrator")
			set_settings(auto_submit_overtime=1)

		_log, ot = self.assert_overtime_log(self.draft_ot_day, 1.5, "Normal", ot_rate(self.draft_ot_day))
		self.assertEqual(ot.docstatus, 0)
		for user in (HR_USER, APPROVER, EMP1):
			frappe.set_user(user)
			self.assertFalse(frappe.has_permission("Overtime Log", "submit", doc=ot, user=user), f"{user} can submit")
		frappe.set_user(HR_MANAGER)
		frappe.get_doc("Overtime Log", ot.name).submit()
		self.assertEqual(frappe.db.get_value("Overtime Log", ot.name, "docstatus"), 1)

	# ---------------------------------------------------------------- emp1
	def test_10_employee_cannot_see_others_or_edit_overtime(self):
		"""Matrix says 'R (own)?' (to confirm): emp1 never sees another employee's Overtime Log and
		cannot create or edit one."""
		other = frappe.get_doc({"doctype": "Overtime Log", "employee": self.no_ot_employee["12 Hour Shift"],
			"overtime_date": self.manual_ot_day, "ot_type": "Normal", "overtime_hours": 1,
			"overtime_rate": 100}).insert(ignore_permissions=True)
		own = frappe.get_doc("Overtime Log", get_log(self.emp1, self.ot_day).overtime)
		frappe.set_user(EMP1)
		self.assertFalse(frappe.has_permission("Overtime Log", "write", doc=own, user=EMP1))
		self.assertFalse(frappe.has_permission("Overtime Log", "create", user=EMP1))
		self.assertFalse(frappe.has_permission("Overtime Log", "read", doc=other, user=EMP1))
		if frappe.has_permission("Overtime Log", "read", user=EMP1):
			employees = set(frappe.get_list("Overtime Log", pluck="employee"))
			self.assertEqual(employees - {self.emp1}, set(), "emp1 sees other employees' Overtime Logs")

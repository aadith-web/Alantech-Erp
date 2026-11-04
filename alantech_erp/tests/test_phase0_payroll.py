# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 7: Payroll Entry and Salary Slip with overtime.

ClickUp: https://app.clickup.com/t/14yr2e56c9z

Matrix (parent task):
    Payroll Entry   HR Manager R C W S X   HR User R C W   Approver -   Employee -
    Salary Slip     HR Manager R W S X     HR User R W     Approver -   Employee R (own), print
    Journal Entry   (payroll accrual, bank entry): does HR Manager need Accounts User?
The HR Manager runs Payroll Entry -> Get Employees -> Submit (creates the Salary Slips) -> Submit Salary
Slip (accrual Journal Entry) -> Make Bank Entry, then cancels and amends emp1's slip. The HR User only
creates a draft Payroll Entry (Custom DocPerm row from setup/payroll.py, which also makes the payroll
payable account of type Payable). emp1 reads and prints their own slip only; setup/salary_access.py keeps
the approver (emp1's Reports To) out of it.

Journal Entry finding (hrms payroll_entry.py): the accrual Journal Entry is saved and submitted with
ignore_permissions, and cancelling the Payroll Entry cancels it the same way, so the HR Manager needs no
Accounts role for the payroll itself. Make Bank Entry only creates a draft Journal Entry (also with
ignore_permissions): opening and submitting it needs Accounts User. test_07 pins this down.

The slip month is last month, paid on attendance: one Absent day and one On Leave (Leave Without Pay)
day, so payment days = working days - 2. Basic and HRA depend on payment days, the fixed allowance does
not; the overtime is (Basic + HRA, full month) / days in month / 8 x 1.5 (overtime_utils.py). Payroll
Settings are switched to "Attendance" for the test and put back afterwards.

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_payroll

Everything created here uses p7.*@example.com addresses, the TEST-P7- employee numbers and TEST-P7
masters, and is removed again in tearDownClass (the Journal Entries and their ledger rows too). Overtime
Settings, Payroll Settings and the payroll payable account type are put back as they were.
"""

import frappe
from frappe.utils import add_days, add_months, flt, get_first_day, get_last_day, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, COMPANY, employee_doc, make_user
from alantech_erp.tests.test_phase0_overtime import restore_overtime, snapshot_overtime

HR_MANAGER = "p7.hr.manager@example.com"
HR_USER = "p7.hr.user@example.com"
APPROVER = "p7.approver@example.com"
EMP1 = "p7.emp1@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

BRANCH = "TEST-P7 Branch"  # keeps Get Employees to the test employees
BASIC = "TEST-P7 Basic"
HRA = "TEST-P7 HRA"
FIXED_ALLOWANCE = "TEST-P7 Fixed Allowance"
OT_COMPONENT = "TEST-P7 Overtime"
# name: (abbr, depends on payment days)
COMPONENTS = {BASIC: ("TP7B", 1), HRA: ("TP7HRA", 1), FIXED_ALLOWANCE: ("TP7FA", 0), OT_COMPONENT: ("TP7OT", 0)}
STRUCTURE = "TEST-P7 Structure"

EARNINGS = {BASIC: 30000, HRA: 12000, FIXED_ALLOWANCE: 3000}
APPLICABLE = (BASIC, HRA)
HOURS_PER_DAY = 8
MULTIPLIER = 1.5
OT_HOURS = 2
LWP_LEAVE_TYPE = "Leave Without Pay"

EXPENSE_ACCOUNT = "Salary - ATIS"
PAYMENT_ACCOUNT = "Cash - ATIS"

# matrix: what each user may do on a Payroll Entry
PAYROLL_ENTRY_RIGHTS = {
	HR_MANAGER: {"read", "create", "write", "submit", "cancel"},
	HR_USER: {"read", "create", "write"},
}
TRANSACTIONS = ("Salary Slip", "Overtime Log", "Attendance", "Salary Structure Assignment")
PAYROLL_SETTINGS = ("payroll_based_on", "consider_unmarked_attendance_as", "email_salary_slip_to_employee")


def company_value(field):
	return frappe.db.get_value("Company", COMPANY, field)


def journal_entries(payroll_entry):
	return frappe.get_all("Journal Entry Account", filters={"reference_type": "Payroll Entry",
		"reference_name": payroll_entry}, pluck="parent", distinct=True)


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P7-%"]}, pluck="name")
	if employees:
		entries = frappe.get_all("Salary Slip", filters={"employee": ["in", employees]}, pluck="payroll_entry")
		entries = {e for e in entries if e} | set(frappe.get_all("Payroll Entry", filters={"branch": BRANCH},
			pluck="name"))
		for entry in entries:
			for je in journal_entries(entry):
				for doctype in ("GL Entry", "Payment Ledger Entry"):
					frappe.db.delete(doctype, {"voucher_type": "Journal Entry", "voucher_no": je})
				frappe.db.delete("Journal Entry Account", {"parent": je})
				frappe.db.delete("Journal Entry", {"name": je})
			frappe.db.delete("Payroll Employee Detail", {"parent": entry})
			frappe.db.delete("Payroll Entry", {"name": entry})
		slips = frappe.get_all("Salary Slip", filters={"employee": ["in", employees]}, pluck="name")
		if slips:
			frappe.db.delete("Salary Detail", {"parent": ["in", slips], "parenttype": "Salary Slip"})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p7.%@example.com"]}, pluck="name"):
		frappe.db.delete("User Permission", {"user": email})
		frappe.db.delete("DocShare", {"user": email})
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
	for name in employees:
		frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
	frappe.db.delete("Salary Detail", {"parent": STRUCTURE, "parenttype": "Salary Structure"})
	frappe.db.delete("Salary Structure", {"name": STRUCTURE})
	for component in COMPONENTS:
		frappe.db.delete("Salary Component Account", {"parent": component})
		frappe.db.delete("Salary Component", {"name": component})
	frappe.db.delete("Branch", {"name": BRANCH})
	frappe.db.commit()


def make_masters():
	for name, (abbr, depends) in COMPONENTS.items():
		frappe.get_doc({"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": abbr,
			"type": "Earning", "depends_on_payment_days": depends,
			"accounts": [{"company": COMPANY, "account": EXPENSE_ACCOUNT}]}).insert(ignore_permissions=True)
	structure = frappe.new_doc("Salary Structure")
	structure.update({"company": COMPANY, "is_active": "Yes", "payroll_frequency": "Monthly",
		"currency": company_value("default_currency")})
	for name, amount in EARNINGS.items():
		structure.append("earnings", {"salary_component": name, "abbr": COMPONENTS[name][0], "amount": amount})
	structure.insert(ignore_permissions=True, set_name=STRUCTURE)
	structure.submit()


def assign_structure(employee, from_date):
	frappe.get_doc({"doctype": "Salary Structure Assignment", "employee": employee, "salary_structure": STRUCTURE,
		"company": COMPANY, "currency": company_value("default_currency"), "from_date": from_date,
		"base": sum(EARNINGS.values()), "payroll_payable_account": company_value("default_payroll_payable_account"),
	}).insert(ignore_permissions=True).submit()


def link_overtime_component():
	"""Overtime Settings: Normal rule paid through the TEST-P7 Overtime earning, base Basic + HRA."""
	settings = frappe.get_doc("Overtime Settings")
	settings.update({"enable_multiple_ot": 0, "base_component_method": "Custom",
		"working_days_base": "Month Days", "working_hours_per_day": HOURS_PER_DAY})
	settings.set("applicable_overtime_component", [{"salary_component": c} for c in APPLICABLE])
	settings.set("overtime_type_rules", [
		{"ot_type": "Normal", "salary_component": OT_COMPONENT, "calculation_method": "Salary Derived",
			"component_method": "Component Wise", "rate_multiplier": MULTIPLIER},
	])
	settings.save(ignore_permissions=True)


def set_payroll_settings(values):
	for field, value in values.items():
		frappe.db.set_single_value("Payroll Settings", field, value)
	frappe.clear_document_cache("Payroll Settings", "Payroll Settings")


def working_days(employee, start, end):
	"""Days of the period that are not on the employee's holiday list."""
	from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

	holidays = set(frappe.get_all("Holiday", filters={"parent": get_holiday_list_for_employee(employee),
		"holiday_date": ["between", [start, end]]}, pluck="holiday_date"))
	day, days = getdate(start), []
	while day <= getdate(end):
		if day not in holidays:
			days.append(day)
		day = add_days(day, 1)
	return days


def mark_attendance(employee, day, status, leave_type=None):
	frappe.get_doc({"doctype": "Attendance", "employee": employee, "company": COMPANY, "attendance_date": day,
		"status": status, "leave_type": leave_type}).insert(ignore_permissions=True).submit()


def payroll_entry_doc(start):
	doc = frappe.new_doc("Payroll Entry")
	doc.update({"company": COMPANY, "posting_date": get_last_day(start), "payroll_frequency": "Monthly",
		"start_date": start, "end_date": get_last_day(start), "branch": BRANCH,
		"currency": company_value("default_currency"), "exchange_rate": 1,
		"payroll_payable_account": company_value("default_payroll_payable_account"),
		"cost_center": company_value("cost_center"), "payment_account": PAYMENT_ACCOUNT})
	return doc


def permissions(doctype, user, doc=None):
	return {p for p in ("read", "create", "write", "submit", "cancel", "delete")
		if frappe.has_permission(doctype, p, doc=doc, user=user)}


def overtime_rows(slip):
	return [d for d in slip.earnings if d.salary_component == OT_COMPONENT]


class TestPhase0Payroll(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		cls.site_overtime = snapshot_overtime()
		cls.site_payroll_settings = frappe.db.get_value("Payroll Settings", None, PAYROLL_SETTINGS, as_dict=True)
		cls.payable_account = company_value("default_payroll_payable_account")
		cls.site_payable_type = frappe.db.get_value("Account", cls.payable_account, "account_type")

		frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			if email == APPROVER:
				continue
			make_user(email, roles)
			emp = employee_doc(f"P7 User{i}", f"TEST-P7-USER{i}", None, user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)

		approver = employee_doc("P7 Approver", "TEST-P7-USER3", None)
		approver.insert(ignore_permissions=True)
		create_user(approver.name, email=APPROVER, create_user_permission=1)
		frappe.get_doc("User", APPROVER).add_roles("Leave Approver")
		cls.employee_of[APPROVER] = approver.name
		frappe.clear_cache(user=APPROVER)

		# emp1 (with a user) and emp2 (without) in the test branch, both reporting to the approver
		emp1 = employee_doc("P7 Emp1", "TEST-P7-EMP1", None, reports_to=approver.name,
			default_shift=DEFAULT_SHIFT, branch=BRANCH)
		emp1.insert(ignore_permissions=True)
		create_user(emp1.name, email=EMP1, create_user_permission=1)
		cls.emp1 = emp1.name
		frappe.clear_cache(user=EMP1)
		emp2 = employee_doc("P7 Emp2", "TEST-P7-EMP2", None, reports_to=approver.name,
			default_shift=DEFAULT_SHIFT, branch=BRANCH)
		emp2.insert(ignore_permissions=True)
		cls.emp2 = emp2.name

		# Phase 0 setup as Administrator: masters, assignments, Overtime / Payroll Settings, attendance
		make_masters()
		cls.start = get_first_day(add_months(today(), -1))
		cls.end = get_last_day(cls.start)
		for employee in (cls.emp1, cls.emp2):
			assign_structure(employee, cls.start)
		link_overtime_component()
		set_payroll_settings({"payroll_based_on": "Attendance", "consider_unmarked_attendance_as": "Present",
			"email_salary_slip_to_employee": 0})
		frappe.db.set_value("Account", cls.payable_account, "account_type", "Payable")

		cls.absent_day, cls.lwp_day, cls.ot_day = working_days(cls.emp1, cls.start, cls.end)[2:5]
		mark_attendance(cls.emp1, cls.absent_day, "Absent")
		mark_attendance(cls.emp1, cls.lwp_day, "On Leave", LWP_LEAVE_TYPE)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		restore_overtime(cls.site_overtime)
		set_payroll_settings(cls.site_payroll_settings)
		frappe.db.set_value("Account", cls.payable_account, "account_type", cls.site_payable_type)
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def payroll_entry(self):
		return frappe.get_doc("Payroll Entry", {"branch": BRANCH, "docstatus": 1})

	def slip_of(self, employee, docstatus=1):
		return frappe.get_doc("Salary Slip", {"employee": employee, "start_date": self.start, "docstatus": docstatus})

	# ---------------------------------------------------------------- site configuration
	def test_01_site_payroll_payable_account(self):
		"""The site's own payroll payable account (before this test changed it) must be of type Payable,
		or Payroll Entry refuses to submit."""
		self.assertEqual(self.site_payable_type, "Payable", f"Account type of {self.payable_account}")

	def test_02_users_have_exactly_their_roles(self):
		for email, expected in {**TEST_USERS, EMP1: {"Employee"}}.items():
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")

	# ---------------------------------------------------------------- overtime for the slip month
	def test_03_overtime_log_created_by_hr_user_submitted_by_hr_manager(self):
		frappe.set_user(HR_USER)
		log = frappe.get_doc({"doctype": "Overtime Log", "employee": self.emp1, "overtime_date": self.ot_day,
			"ot_type": "Normal", "overtime_hours": OT_HOURS, "overtime_rate": 100}).insert()
		frappe.set_user(HR_MANAGER)
		log = frappe.get_doc("Overtime Log", log.name)
		log.submit()
		self.assertEqual((log.docstatus, log.owner), (1, HR_USER))

	# ---------------------------------------------------------------- HR User
	def test_04_hr_user_creates_payroll_entry_without_submit_or_cancel(self):
		frappe.set_user(HR_USER)
		doc = payroll_entry_doc(self.start)
		doc.insert()
		doc.fill_employee_details()
		doc.save()
		self.assertEqual({d.employee for d in doc.employees}, {self.emp1, self.emp2})
		self.assertEqual(permissions("Payroll Entry", HR_USER, doc) - {"delete"}, PAYROLL_ENTRY_RIGHTS[HR_USER])
		self.assertRaises(frappe.PermissionError, doc.submit)
		frappe.set_user("Administrator")
		frappe.delete_doc("Payroll Entry", doc.name, force=1)

	# ---------------------------------------------------------------- HR Manager
	def test_05_hr_manager_runs_payroll_entry(self):
		"""Payroll Entry -> Get Employees -> Submit, which creates the draft Salary Slips."""
		frappe.set_user(HR_MANAGER)
		doc = payroll_entry_doc(self.start)
		doc.insert()
		self.assertEqual(permissions("Payroll Entry", HR_MANAGER, doc) - {"delete"}, PAYROLL_ENTRY_RIGHTS[HR_MANAGER])
		doc.fill_employee_details()
		doc.save()
		self.assertEqual({d.employee for d in doc.employees}, {self.emp1, self.emp2})
		doc.submit()
		doc.reload()
		self.assertFalse(doc.error_message, doc.error_message)
		self.assertTrue(doc.salary_slips_created)
		slips = frappe.get_all("Salary Slip", filters={"payroll_entry": doc.name}, fields=["employee", "docstatus", "owner"])
		self.assertEqual({(s.employee, s.docstatus, s.owner) for s in slips},
			{(self.emp1, 0, HR_MANAGER), (self.emp2, 0, HR_MANAGER)})

	def test_06_slip_has_attendance_and_overtime(self):
		"""Payment days = working days - 1 Absent - 1 LWP; Basic and HRA prorated; overtime on the full base."""
		slip = self.slip_of(self.emp1, docstatus=0)
		self.assertEqual(slip.total_working_days, len(working_days(self.emp1, self.start, self.end)))
		self.assertEqual((flt(slip.absent_days), flt(slip.leave_without_pay)), (1, 1))
		self.assertEqual(flt(slip.payment_days), slip.total_working_days - 2)
		amounts = {d.salary_component: d.amount for d in slip.earnings}
		for component in APPLICABLE:
			expected = EARNINGS[component] * slip.payment_days / slip.total_working_days
			self.assertAlmostEqual(flt(amounts[component]), expected, delta=1, msg=f"{component} not prorated")
		self.assertEqual(flt(amounts[FIXED_ALLOWANCE]), EARNINGS[FIXED_ALLOWANCE])

		rows = overtime_rows(slip)
		self.assertEqual(len(rows), 1, "no Overtime earning on the slip")
		expected = flt(OT_HOURS * (EARNINGS[BASIC] + EARNINGS[HRA]) / self.end.day / HOURS_PER_DAY * MULTIPLIER, 2)
		self.assertEqual(flt(rows[0].amount, 2), expected)
		self.assertEqual(flt(rows[0].custom_overtime_hours), OT_HOURS)

	def test_07_hr_manager_submits_slips_and_journal_entries(self):
		"""Submit Salary Slip books the accrual Journal Entry without any Accounts role; Make Bank Entry
		only drafts one, which the HR Manager cannot open or submit without Accounts User."""
		frappe.set_user(HR_MANAGER)
		doc = self.payroll_entry()
		doc.submit_salary_slips()
		doc.reload()
		self.assertFalse(doc.error_message, doc.error_message)
		self.assertTrue(doc.salary_slips_submitted)
		self.assertEqual(set(frappe.get_all("Salary Slip", filters={"payroll_entry": doc.name}, pluck="docstatus")), {1})

		accrual = journal_entries(doc.name)
		self.assertEqual(len(accrual), 1, "no accrual Journal Entry")
		self.assertEqual(frappe.db.get_value("Journal Entry", accrual[0], ["docstatus", "owner"]), (1, HR_MANAGER))

		doc.make_bank_entry()
		bank = set(journal_entries(doc.name)) - set(accrual)
		self.assertEqual(len(bank), 1, "no bank entry")
		bank_entry = frappe.get_doc("Journal Entry", bank.pop())
		self.assertEqual(bank_entry.docstatus, 0)
		self.assertEqual(permissions("Journal Entry", HR_MANAGER, bank_entry), set(),
			"HR Manager can work on the bank entry without Accounts User")

	# ---------------------------------------------------------------- emp1 / approver
	def test_08_emp1_reads_and_prints_own_slip_only(self):
		from frappe.www.printview import validate_print_permission

		own, other = self.slip_of(self.emp1), self.slip_of(self.emp2)
		frappe.set_user(EMP1)
		self.assertEqual(permissions("Salary Slip", EMP1, own), {"read"})
		self.assertTrue(frappe.has_permission("Salary Slip", "print", doc=own, user=EMP1))
		validate_print_permission(own)
		self.assertEqual(set(frappe.get_list("Salary Slip", pluck="employee")), {self.emp1})
		self.assertFalse(frappe.has_permission("Salary Slip", "read", doc=other, user=EMP1))
		self.assertEqual(permissions("Payroll Entry", EMP1), set())

		frappe.set_user(APPROVER)
		self.assertEqual(frappe.get_list("Salary Slip", pluck="name"), [], "the approver sees salary slips")
		self.assertFalse(frappe.has_permission("Salary Slip", "read", doc=own, user=APPROVER))
		self.assertEqual(permissions("Payroll Entry", APPROVER), set())

	# ---------------------------------------------------------------- cancel and amend
	def test_09_hr_manager_cancels_and_amends_slip(self):
		"""Done when: emp1 has a submitted Salary Slip with overtime, created with only the matrix roles."""
		frappe.set_user(HR_MANAGER)
		original = self.slip_of(self.emp1)
		original.cancel()
		self.assertEqual(frappe.db.get_value("Salary Slip", original.name, "docstatus"), 2)

		amended = frappe.copy_doc(original, ignore_no_copy=False)  # as the Amend button does
		amended.update({"docstatus": 0, "amended_from": original.name})
		amended.insert()
		amended.submit()
		self.assertEqual((amended.docstatus, amended.owner, amended.amended_from), (1, HR_MANAGER, original.name))
		self.assertEqual(flt(overtime_rows(amended)[0].amount, 2), flt(overtime_rows(original)[0].amount, 2))
		self.assertEqual(flt(amended.net_pay, 2), flt(original.net_pay, 2))

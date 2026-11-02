# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""HR-002-6 Phase 0, Step 6: salary components, salary structure and assignment.

ClickUp: https://app.clickup.com/t/14yr2e56c9y

Matrix (parent task, as confirmed by the team after the first run):
    Salary Component              HR Manager R C W     HR User R C W         Approver R   Employee R
    Salary Structure              HR Manager R C W S   HR User R C W S X D   Approver -   Employee -
    Salary Structure Assignment   HR Manager R C W S   HR User R C W S       Approver R (own)   Employee R (own)
The Employee role's reads come from a Custom DocPerm row (Salary Component) and standard HRMS
(Salary Structure Assignment); the Approver gets them through its Employee role. Leave Approver is only
for approving leave. The Employee User Permission alone is not enough (it also allows everyone below
the user in the Reports To tree), so setup/salary_access.py keeps salary records to the user's own.
The HR Manager creates the components (Basic, HRA, a fixed allowance and the Overtime earning) and the
structure; HR Manager and HR User each submit a Salary Structure Assignment for emp1. The Overtime
component is linked in Overtime Settings (never in the structure, see overtime_utils.py), so an
Overtime Log of emp1 shows up as an earning on the slip. Every user holds only their matrix roles and
every permission check runs as the user under test (no ignore_permissions).

Run:
    bench --site alantech.localhost set-config allow_tests true
    bench --site alantech.localhost run-tests --module alantech_erp.tests.test_phase0_salary_structure

Everything created here uses p6.*@example.com addresses, the TEST-P6- employee numbers and TEST-P6
masters, and is removed again in tearDownClass. Overtime Settings are put back as they were.
"""

import frappe
from frappe.utils import add_days, add_months, flt, get_first_day, get_last_day, getdate, today

try:  # v16
	from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
	from frappe.tests.utils import FrappeTestCase as TestCase

from alantech_erp.setup.employee_user import create_user
from alantech_erp.setup.shifts import DEFAULT_SHIFT, OVERTIME_COMPONENT
from alantech_erp.tests.test_phase0_employee_user import AUTOMATIC_ROLES, COMPANY, employee_doc, make_user
from alantech_erp.tests.test_phase0_overtime import restore_overtime, snapshot_overtime

HR_MANAGER = "p6.hr.manager@example.com"
HR_USER = "p6.hr.user@example.com"
APPROVER = "p6.approver@example.com"
EMP1 = "p6.emp1@example.com"

TEST_USERS = {
	HR_MANAGER: {"HR Manager", "Employee"},
	HR_USER: {"HR User", "Employee"},
	APPROVER: {"Employee", "Leave Approver"},
}

BASIC = "TEST-P6 Basic"
HRA = "TEST-P6 HRA"
FIXED_ALLOWANCE = "TEST-P6 Fixed Allowance"
OT_COMPONENT = "TEST-P6 Overtime"
COMPONENTS = {BASIC: "TP6B", HRA: "TP6HRA", FIXED_ALLOWANCE: "TP6FA", OT_COMPONENT: "TP6OT"}
STRUCTURE = "TEST-P6 Structure"

# monthly: gross 45000; the fixed allowance is left out of the overtime base
EARNINGS = {BASIC: 30000, HRA: 12000, FIXED_ALLOWANCE: 3000}
APPLICABLE = (BASIC, HRA)
HOURS_PER_DAY = 8
MULTIPLIER = 1.5
OT_HOURS = 2

ASSIGNMENT = "Salary Structure Assignment"
# confirmed matrix: what HR User may do on the masters, and what Employee / Approver may read
HR_USER_MASTERS = {
	"Salary Component": {"read", "create", "write"},
	"Salary Structure": {"read", "create", "write", "submit", "cancel", "delete"},
}
SELF_SERVICE_READ = {"Salary Component": True, "Salary Structure": False, ASSIGNMENT: True}
TRANSACTIONS = ("Salary Slip", "Overtime Log", ASSIGNMENT)


def currency():
	return frappe.db.get_value("Company", COMPANY, "default_currency")


def cleanup():
	frappe.set_user("Administrator")
	employees = frappe.get_all("Employee", filters={"employee_number": ["like", "TEST-P6-%"]}, pluck="name")
	if employees:
		slips = frappe.get_all("Salary Slip", filters={"employee": ["in", employees]}, pluck="name")
		if slips:
			frappe.db.delete("Salary Detail", {"parent": ["in", slips], "parenttype": "Salary Slip"})
		for doctype in TRANSACTIONS:  # submitted documents: delete_doc would refuse them
			frappe.db.delete(doctype, {"employee": ["in", employees]})
	for name in employees:
		frappe.db.set_value("Employee", name, "user_id", None)
	for email in frappe.get_all("User", filters={"name": ["like", "p6.%@example.com"]}, pluck="name"):
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
	frappe.db.commit()


def component(name):
	return frappe.get_doc({"doctype": "Salary Component", "salary_component": name,
		"salary_component_abbr": COMPONENTS[name], "type": "Earning", "depends_on_payment_days": 0})


def structure_doc():
	doc = frappe.new_doc("Salary Structure")
	doc.update({"company": COMPANY, "is_active": "Yes", "payroll_frequency": "Monthly",
		"currency": currency()})
	for name, amount in EARNINGS.items():
		doc.append("earnings", {"salary_component": name, "abbr": COMPONENTS[name], "amount": amount})
	return doc


def assignment(employee, from_date):
	return frappe.get_doc({"doctype": ASSIGNMENT, "employee": employee, "salary_structure": STRUCTURE,
		"company": COMPANY, "currency": currency(), "from_date": from_date, "base": sum(EARNINGS.values()),
		"payroll_payable_account": frappe.db.get_value("Company", COMPANY, "default_payroll_payable_account")})


def link_overtime_component():
	"""Overtime Settings: Normal rule paid through the TEST-P6 Overtime earning, base Basic + HRA."""
	settings = frappe.get_doc("Overtime Settings")
	settings.update({"enable_multiple_ot": 0, "base_component_method": "Custom",
		"working_days_base": "Month Days", "working_hours_per_day": HOURS_PER_DAY})
	settings.set("applicable_overtime_component", [{"salary_component": c} for c in APPLICABLE])
	settings.set("overtime_type_rules", [
		{"ot_type": "Normal", "salary_component": OT_COMPONENT, "calculation_method": "Salary Derived",
			"component_method": "Component Wise", "rate_multiplier": MULTIPLIER},
	])
	settings.save(ignore_permissions=True)


def permissions(doctype, user, doc=None):
	return {p for p in ("read", "create", "write", "submit", "cancel", "delete")
		if frappe.has_permission(doctype, p, doc=doc, user=user)}


class TestPhase0SalaryStructure(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		cleanup()
		cls.site_overtime = snapshot_overtime()

		cls.employee_of = {}
		for i, (email, roles) in enumerate(TEST_USERS.items(), start=1):
			if email == APPROVER:
				continue
			make_user(email, roles)
			emp = employee_doc(f"P6 User{i}", f"TEST-P6-USER{i}", None, user_id=email)
			emp.insert(ignore_permissions=True)
			cls.employee_of[email] = emp.name
			frappe.clear_cache(user=email)

		# the approver is an ordinary employee user like on the site (restricted to their own Employee
		# record), plus Leave Approver: the role is only for approving leave
		approver = employee_doc("P6 Approver", "TEST-P6-USER3", None)
		approver.insert(ignore_permissions=True)
		create_user(approver.name, email=APPROVER, create_user_permission=1)
		frappe.get_doc("User", APPROVER).add_roles("Leave Approver")
		cls.employee_of[APPROVER] = approver.name
		frappe.clear_cache(user=APPROVER)

		emp1 = employee_doc("P6 Emp1", "TEST-P6-EMP1", None, reports_to=cls.employee_of[APPROVER],
			default_shift=DEFAULT_SHIFT)
		emp1.insert(ignore_permissions=True)
		create_user(emp1.name, email=EMP1, create_user_permission=1)
		cls.emp1 = emp1.name
		frappe.clear_cache(user=EMP1)

		# HR Manager assigns from last month (the slip month), HR User from this month
		cls.manager_from = get_first_day(add_months(today(), -1))
		cls.user_from = get_first_day(today())
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		restore_overtime(cls.site_overtime)
		cleanup()
		frappe.flags.mute_emails = False
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---------------------------------------------------------------- site configuration
	def test_01_site_overtime_component_linked(self):
		"""The site's own Overtime Settings (before this test changed them): the OT earning is the
		Normal rule's component, and every applicable component exists."""
		settings = self.site_overtime["settings"]
		rules = {r.ot_type: r.salary_component for r in settings.overtime_type_rules}
		self.assertEqual(rules.get("Normal"), OVERTIME_COMPONENT[0], "Normal rule's salary component")
		self.assertEqual(frappe.db.get_value("Salary Component", OVERTIME_COMPONENT[0], "type"), "Earning")
		applicable = [c.salary_component for c in settings.applicable_overtime_component]
		self.assertTrue(applicable, "no Applicable Overtime Components")
		for name in applicable:
			self.assertTrue(frappe.db.exists("Salary Component", name), f"{name} missing")

	def test_02_users_have_exactly_their_roles(self):
		for email, expected in {**TEST_USERS, EMP1: {"Employee"}}.items():
			roles = set(frappe.get_roles(email)) - AUTOMATIC_ROLES
			self.assertEqual(roles, expected, f"{email} roles")

	# ---------------------------------------------------------------- HR Manager
	def test_03_hr_manager_creates_components(self):
		frappe.set_user(HR_MANAGER)
		for name in COMPONENTS:
			doc = component(name).insert()
			self.assertEqual(doc.owner, HR_MANAGER)

	def test_04_hr_manager_creates_and_submits_structure(self):
		frappe.set_user(HR_MANAGER)
		doc = structure_doc().insert(set_name=STRUCTURE)
		doc.submit()
		self.assertEqual(frappe.db.get_value("Salary Structure", STRUCTURE, ["docstatus", "owner"]), (1, HR_MANAGER))
		earnings = {d.salary_component for d in doc.earnings}
		self.assertNotIn(OT_COMPONENT, earnings, "the OT component must stay out of the structure")

	def test_05_hr_manager_assigns_structure_to_emp1(self):
		"""Done when: emp1 has a submitted Salary Structure Assignment created with only the matrix roles."""
		frappe.set_user(HR_MANAGER)
		doc = assignment(self.emp1, self.manager_from).insert()
		doc.submit()
		self.assertEqual((doc.docstatus, doc.owner, doc.base), (1, HR_MANAGER, sum(EARNINGS.values())))

	# ---------------------------------------------------------------- HR User
	def test_06_hr_user_assigns_structure_to_emp1(self):
		frappe.set_user(HR_USER)
		self.assertTrue(frappe.has_permission("Salary Structure", "read", doc=STRUCTURE, user=HR_USER))
		doc = assignment(self.emp1, self.user_from).insert()
		doc.submit()
		self.assertEqual((doc.docstatus, doc.owner), (1, HR_USER))

	def test_07_hr_user_permissions_on_components_and_structure(self):
		frappe.set_user(HR_USER)
		docs = {"Salary Component": BASIC, "Salary Structure": STRUCTURE}
		actual = {doctype: permissions(doctype, HR_USER, frappe.get_doc(doctype, name))
			for doctype, name in docs.items()}
		self.assertEqual(actual, HR_USER_MASTERS, "HR User on Salary Component / Salary Structure")

	# ---------------------------------------------------------------- Employee / Approver
	def test_08_employee_and_approver_read_only(self):
		"""Read on Salary Component and their own Salary Structure Assignment, nothing on Salary
		Structure, and never more than read. Leave Approver gives no access to anyone's salary."""
		emp1_assignments = frappe.get_all(ASSIGNMENT, filters={"employee": self.emp1, "docstatus": 1}, pluck="name")
		self.assertTrue(emp1_assignments, "emp1 has no submitted Salary Structure Assignment")
		own_employee = {EMP1: self.emp1, APPROVER: self.employee_of[APPROVER]}
		for user in (EMP1, APPROVER):
			frappe.set_user(user)
			for doctype, can_read in SELF_SERVICE_READ.items():
				self.assertEqual(permissions(doctype, user), {"read"} if can_read else set(), f"{user} on {doctype}")
			others = set(frappe.get_list(ASSIGNMENT, pluck="employee")) - {own_employee[user]}
			self.assertEqual(others, set(), f"{user} sees other employees' Salary Structure Assignments")
		frappe.set_user(EMP1)
		self.assertTrue(frappe.has_permission(ASSIGNMENT, "read", doc=emp1_assignments[0], user=EMP1))
		frappe.set_user(APPROVER)
		self.assertFalse(frappe.has_permission(ASSIGNMENT, "read", doc=emp1_assignments[0], user=APPROVER),
			"the approver can read emp1's Salary Structure Assignment")

	# ---------------------------------------------------------------- overtime into the slip
	def test_09_overtime_flows_into_the_slip(self):
		"""An Overtime Log last month shows up on emp1's slip as the TEST-P6 Overtime earning at
		(Basic + HRA) / days in month / 8 x 1.5. The slip itself is Step 7: built here as Administrator."""
		from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

		link_overtime_component()
		ot_day = add_days(self.manager_from, 14)
		frappe.get_doc({"doctype": "Overtime Log", "employee": self.emp1, "overtime_date": ot_day,
			"ot_type": "Normal", "overtime_hours": OT_HOURS, "overtime_rate": 100}).insert().submit()

		slip = make_salary_slip(STRUCTURE, employee=self.emp1, posting_date=get_last_day(self.manager_from))
		slip.insert()
		self.assertEqual(getdate(slip.start_date), getdate(self.manager_from))
		rows = [d for d in slip.earnings if d.salary_component == OT_COMPONENT]
		self.assertEqual(len(rows), 1, "no Overtime earning on the slip")
		days = getdate(get_last_day(self.manager_from)).day
		expected = flt(OT_HOURS * (EARNINGS[BASIC] + EARNINGS[HRA]) / days / HOURS_PER_DAY * MULTIPLIER, 2)
		self.assertEqual(flt(rows[0].amount, 2), expected)
		self.assertEqual(flt(rows[0].custom_overtime_hours), OT_HOURS)

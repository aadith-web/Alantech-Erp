"""Demo data for an Alantech demo / UAT site: users, employees, HRMS and CRM masters, sales persons,
customers, leads and deals, company assets and employee asset handovers (issues, returns with
inspection, a damaged return with its Asset Repair, a draft issue and a leaving employee who still
holds an asset), so every flow can be walked through as the right user.

Run (safe to re-run: every record is looked up first and only created when missing):
    bench --site <site> execute alantech_erp.demo.data.execute
or in the desk System Console (Frappe Cloud):
    from alantech_erp.demo import data; data.execute()

The patch alantech_erp.patches.v16.demo_data loads it at the end of `bench migrate` (through the
last after_migrate hook, after the app's own setup), but only on sites whose site_config.json has
"alantech_demo_data": 1, so it can never put demo records into the live company.

Everything created here is easy to recognise:
    Employees  Employee Number DEMO-001 ... DEMO-020
    Users      <name>@alantech.example (the .example domain never receives mail),
               password DEMO_PASSWORD (or "alantech_demo_password" in site_config.json)
    Parties    customer / lead company names end in "(Demo)"
    Assets     asset names end in "(Demo)"; handovers have remarks starting "(Demo) H01:" ...

Users get their roles the normal way: the Employee hooks create the user and apply the
designation's role profile (org_structure.py), and Sales employees get a Sales Person
(sales/sales_person.py). Nothing here bypasses those rules, so the demo shows the real setup.
"""

import re

import frappe
from frappe.utils import add_days, getdate, today
from frappe.utils.nestedset import get_root_of

from alantech_erp.setup.shifts import COMPANY as ALANTECH_COMPANY

DEMO_TAG = "(Demo)"
EMAIL_DOMAIN = "alantech.example"
DEMO_PASSWORD = "Alantech@Demo26"
EMP_PREFIX = "DEMO-"

# ---------------------------------------------------------------------------------- HR masters
# the company's actual branches (Branch master on the live site); territories stay the sales regions
HEAD_OFFICE = "Head Office - Kochi"
FACTORY = "Factory - Agnamaly"
BRANCHES = [HEAD_OFFICE, FACTORY, "Mookkannoor", "Thevara", "Puliyanam"]
EMPLOYMENT_TYPES = ["Full-time", "Probation", "Contract", "Intern"]

# leave type: (max days per year, is carry forward, is LWP, for male, for female)
LEAVE_TYPES = {
	"Casual Leave": (12, 0, 0, 1, 1),
	"Sick Leave": (12, 0, 0, 1, 1),
	"Earned Leave": (15, 1, 0, 1, 1),
	"Maternity Leave": (182, 0, 0, 0, 1),
	"Leave Without Pay": (0, 0, 1, 1, 1),
}
LEAVE_POLICY = "Alantech Standard Leave Policy"
LEAVE_POLICY_DAYS = {"Casual Leave": 12, "Sick Leave": 12, "Earned Leave": 15}

EXPENSE_CLAIM_TYPES = ["Travel", "Food", "Accommodation", "Fuel", "Site Visit"]

# salary component: (abbr, type, formula or None, fixed amount, depends on payment days)
# HRMS: a formula built on another payment-days component must not depend on payment days itself
SALARY_COMPONENTS = {
	"Basic": ("B", "Earning", "base * 0.5", 0, 1),
	"House Rent Allowance": ("HRA", "Earning", "B * 0.4", 0, 0),
	"Conveyance Allowance": ("CA", "Earning", None, 1600, 1),
	"Special Allowance": ("SA", "Earning", "base - B - HRA - CA", 0, 0),
	"Provident Fund": ("PF", "Deduction", "B * 0.12", 0, 0),
	"Professional Tax": ("PT", "Deduction", None, 200, 0),
}
SALARY_STRUCTURE = "Alantech Staff Salary"

# --------------------------------------------------------------------------------- employees
# (number, first, last, gender, designation, branch, email user (None: no login), monthly base, shift)
# Order matters: managers first, so Reports To, approvers and the Sales Person tree fill top-down.
EMPLOYEES = [
	("001", "Rajesh", "Menon", "Male", "Managing Director", HEAD_OFFICE, "md", 250000, None),
	("002", "Anitha", "Nair", "Female", "HR Manager", HEAD_OFFICE, "hr.manager", 90000, None),
	("003", "Divya", "Thomas", "Female", "HR Executive", HEAD_OFFICE, "hr.executive", 40000, None),
	("004", "Suresh", "Pillai", "Male", "Finance Manager", HEAD_OFFICE, "finance", 110000, None),
	("005", "Neethu", "Joseph", "Female", "Accounts Executive", HEAD_OFFICE, "accounts", 35000, None),
	("006", "Arun", "Kumar", "Male", "Sales Head", HEAD_OFFICE, "sales.head", 150000, None),
	("007", "Vivek", "Raghavan", "Male", "Sales Manager", HEAD_OFFICE, "sales.manager", 100000, None),
	("008", "Akhil", "Das", "Male", "Sales Engineer", "Thevara", "sales.kerala", 45000, None),
	("009", "Sneha", "Reddy", "Female", "Sales Engineer", "Puliyanam", "sales.hyderabad", 45000, None),
	("010", "Rahul", "Varma", "Male", "Proposal Engineer", HEAD_OFFICE, "proposal", 55000, None),
	("011", "Meera", "Krishnan", "Female", "Marketing Manager", HEAD_OFFICE, "marketing", 85000, None),
	("012", "Joseph", "Mathew", "Male", "Operations Manager", HEAD_OFFICE, "operations", 130000, None),
	("013", "Kiran", "Babu", "Male", "Design Head", "Mookkannoor", "design.head", 95000, None),
	("014", "Anjali", "Menon", "Female", "Design Engineer", "Mookkannoor", "design", 50000, None),
	("015", "Manoj", "Kumar", "Male", "Production Manager", FACTORY, "production", 95000, None),
	("016", "Biju", "Varghese", "Male", "Production Supervisor", FACTORY, "supervisor", 40000, None),
	("017", "Shibu", "Paul", "Male", "Fitter", FACTORY, "fitter", 22000, "12 Hour Shift"),
	("018", "Ramesh", "Kannan", "Male", "Welder", FACTORY, None, 22000, "12 Hour Shift"),
	("019", "Prakash", "Nair", "Male", "Store Keeper", FACTORY, "store", 32000, None),
	("020", "Jithin", "George", "Male", "Service Engineer", "Puliyanam", "service", 38000, None),
]

# ---------------------------------------------------------------------------------- CRM masters
TERRITORIES = {"India": ["Kerala", "Bangalore", "Hyderabad"], None: ["UAE"]}  # parent -> children
CUSTOMER_GROUPS = ["Industrial", "Pharmaceutical", "Food & Beverage", "Hospitality", "Government"]
INDUSTRIES = [
	"Pharmaceutical", "Food & Beverage", "Textile", "Power & Energy", "Hospitality", "Chemicals",
	"Municipal Water",
]
LEAD_SOURCES = ["Website", "Referral", "Exhibition", "Cold Call", "Existing Customer", "IndiaMART"]
OPPORTUNITY_TYPES = ["New Plant", "AMC", "Spares", "Retrofit"]
SALES_STAGES = ["Prospecting", "Qualification", "Needs Analysis", "Proposal/Price Quote", "Negotiation/Review"]
LOST_REASONS = ["Price too high", "Lost to competitor", "Project dropped", "Delivery time"]

ITEM_GROUPS = ["Water Treatment Plants", "Services", "Spares"]
# code: (name, group, HSN/SAC, stock item, selling rate)
ITEMS = {
	"WTP-RO-10": ("RO Plant 10 m3/h", "Water Treatment Plants", "842121", 0, 1850000),
	"WTP-UF-20": ("Ultrafiltration Plant 20 m3/h", "Water Treatment Plants", "842121", 0, 2450000),
	"STP-MBBR-100": ("Sewage Treatment Plant (MBBR) 100 KLD", "Water Treatment Plants", "842121", 0, 1600000),
	"ETP-50": ("Effluent Treatment Plant 50 KLD", "Water Treatment Plants", "842121", 0, 2200000),
	"AMC-WTP": ("Annual Maintenance Contract - Water Treatment Plant", "Services", "998719", 0, 180000),
	"SPR-RO-8040": ("RO Membrane 8040", "Spares", "842199", 1, 38000),
}
HSN_DESCRIPTIONS = {
	"842121": "Machinery and apparatus for filtering or purifying water",
	"842199": "Parts of filtering or purifying machinery",
	"998719": "Maintenance and repair services of other machinery and equipment",
}

# customer: (group, territory, industry, account owner (employee no.), contact, city, state, pincode)
CUSTOMERS = {
	f"Kerala Pharma Industries {DEMO_TAG}": (
		"Pharmaceutical", "Kerala", "Pharmaceutical", "008", ("Sajan", "Kurian"), "Kochi", "Kerala", "682030"),
	f"Deccan Foods Pvt Ltd {DEMO_TAG}": (
		"Food & Beverage", "Hyderabad", "Food & Beverage", "009", ("Lakshmi", "Rao"), "Hyderabad", "Telangana", "500032"),
	f"Garden City Hotels {DEMO_TAG}": (
		"Hospitality", "Bangalore", "Hospitality", "009", ("Naveen", "Gowda"), "Bengaluru", "Karnataka", "560001"),
	f"Gulf Desal Contracting LLC {DEMO_TAG}": (
		"Industrial", "UAE", "Municipal Water", "007", ("Omar", "Haddad"), "Dubai", None, None),
}

# lead: (first, last, company, industry, territory, source, status, owner employee no.)
LEADS = [
	("Anil", "Kumar", f"Malabar Textiles {DEMO_TAG}", "Textile", "Kerala", "Exhibition", "Open", "008"),
	("Priya", "Sharma", f"Hyderabad Chem Labs {DEMO_TAG}", "Chemicals", "Hyderabad", "Website", "Replied", "009"),
	("Farhan", "Ali", f"Emirates Bottling Co {DEMO_TAG}", "Food & Beverage", "UAE", "Referral", "Interested", "007"),
	("Deepa", "Rao", f"Whitefield Tech Park {DEMO_TAG}", "Hospitality", "Bangalore", "Cold Call", "Lead", "009"),
	("Thomas", "Kurian", f"Cochin Water Board {DEMO_TAG}", "Municipal Water", "Kerala", "IndiaMART", "Lead", "008"),
	("Ravi", "Teja", f"Godavari Power {DEMO_TAG}", "Power & Energy", "Hyderabad", "Referral", "Interested", "009"),
]

# deal: (from, party, type, stage, item, qty, owner employee no., days to close)
DEALS = [
	("Customer", f"Kerala Pharma Industries {DEMO_TAG}", "New Plant", "Needs Analysis", "WTP-RO-10", 1, "008", 30),
	("Customer", f"Deccan Foods Pvt Ltd {DEMO_TAG}", "New Plant", "Proposal/Price Quote", "STP-MBBR-100", 1, "009", 21),
	("Lead", f"Emirates Bottling Co {DEMO_TAG}", "New Plant", "Qualification", "WTP-UF-20", 1, "007", 45),
	("Customer", f"Garden City Hotels {DEMO_TAG}", "AMC", "Negotiation/Review", "AMC-WTP", 1, "009", 14),
]

# Quotations above this grand total need Level 2 approval (only set when the site has no limit):
# the RO deal (18.5 lakh) stays at Level 1, the UF deal (24.5 lakh) goes to Level 2.
LEVEL_2_LIMIT = 2000000

# ------------------------------------------------------------------- assets and asset handover
# Locations mirror the branches, so an asset sits where the employee who uses it works.
ASSET_ITEM_GROUP = "Fixed Assets"
# category: words to find its Fixed Asset account in the chart of accounts (first match wins;
# any Fixed Asset ledger is the fallback)
ASSET_CATEGORIES = {
	"IT Equipment": ("Electronic", "Computer", "Office Equipment"),
	"Mobile Phones": ("Electronic", "Office Equipment"),
	"Vehicles": ("Vehicle", "Capital Equipment"),
	"Tools & Equipment": ("Plant", "Machiner", "Capital Equipment"),
}
# item code: (item name, category)
ASSET_ITEMS = {
	"FA-LAPTOP": ("Dell Latitude 5440 Laptop", "IT Equipment"),
	"FA-WORKSTATION": ("HP Z2 G9 CAD Workstation", "IT Equipment"),
	"FA-MOBILE": ("Samsung Galaxy A35 Mobile Phone", "Mobile Phones"),
	"FA-BIKE": ("Honda Shine Motorcycle", "Vehicles"),
	"FA-PICKUP": ("Mahindra Bolero Pickup", "Vehicles"),
	"FA-WELDING": ("ESAB Arc Welding Machine", "Tools & Equipment"),
	"FA-TOOLKIT": ("Bosch Cordless Power Tool Kit", "Tools & Equipment"),
	"FA-WQ-KIT": ("Portable Water Quality Test Kit (pH / TDS / Conductivity)", "Tools & Equipment"),
}
# key: (item code, asset name, location, purchase amount, bought this many days ago)
# The key goes into the asset name, so a re-run finds the asset again.
ASSETS = {
	"L01": ("FA-LAPTOP", "Laptop L01", HEAD_OFFICE, 78000, 540),
	"L02": ("FA-LAPTOP", "Laptop L02", HEAD_OFFICE, 78000, 540),
	"L03": ("FA-LAPTOP", "Laptop L03", HEAD_OFFICE, 78000, 540),
	"L04": ("FA-LAPTOP", "Laptop L04", HEAD_OFFICE, 78000, 480),
	"L05": ("FA-LAPTOP", "Laptop L05", HEAD_OFFICE, 78000, 480),
	"L06": ("FA-LAPTOP", "Laptop L06", "Mookkannoor", 78000, 480),
	"L07": ("FA-LAPTOP", "Laptop L07", HEAD_OFFICE, 82000, 120),
	"L08": ("FA-LAPTOP", "Laptop L08", HEAD_OFFICE, 82000, 120),
	"W01": ("FA-WORKSTATION", "CAD Workstation W01", "Mookkannoor", 185000, 500),
	"M01": ("FA-MOBILE", "Mobile M01", HEAD_OFFICE, 30000, 420),
	"M02": ("FA-MOBILE", "Mobile M02", HEAD_OFFICE, 30000, 420),
	"M03": ("FA-MOBILE", "Mobile M03", HEAD_OFFICE, 30000, 420),
	"M04": ("FA-MOBILE", "Mobile M04", HEAD_OFFICE, 30000, 420),
	"M05": ("FA-MOBILE", "Mobile M05", HEAD_OFFICE, 30000, 420),
	"V01": ("FA-BIKE", "Motorcycle V01 (KL-07-DM-4521)", FACTORY, 92000, 600),
	"V02": ("FA-PICKUP", "Pickup V02 (KL-41-DM-8834)", FACTORY, 965000, 700),
	"T01": ("FA-WELDING", "Welding Machine T01", FACTORY, 65000, 650),
	"T02": ("FA-TOOLKIT", "Power Tool Kit T02", FACTORY, 28000, 650),
	"T03": ("FA-TOOLKIT", "Power Tool Kit T03", FACTORY, 28000, 650),
	"T04": ("FA-TOOLKIT", "Power Tool Kit T04", FACTORY, 28000, 300),
	"K01": ("FA-WQ-KIT", "Water Test Kit K01", HEAD_OFFICE, 42000, 400),
	"K02": ("FA-WQ-KIT", "Water Test Kit K02", FACTORY, 42000, 400),
}
# Handovers in date order (each one must be later than the asset's last movement).
# key: (type, employee no., days ago, {asset key: None | "Good" | damage description},
#       return-to location (Receipt), submit)
# A Receipt with conditions is inspected; a damaged asset gets an Asset Repair (Pending).
# Left free for a live demo: L08 and V02 (never issued).
HANDOVERS = {
	"H01": ("Issue", "001", 300, {"L01": None, "M01": None}, None, 1),
	"H02": ("Issue", "002", 300, {"L02": None}, None, 1),
	"H03": ("Issue", "006", 280, {"L03": None, "M02": None}, None, 1),
	"H04": ("Issue", "008", 250, {"L04": None, "M03": None, "K01": None}, None, 1),
	"H05": ("Issue", "009", 250, {"L05": None, "M04": None}, None, 1),
	"H06": ("Issue", "013", 240, {"W01": None}, None, 1),
	"H07": ("Issue", "014", 240, {"L06": None}, None, 1),
	"H08": ("Issue", "018", 200, {"T01": None}, None, 1),
	"H09": ("Issue", "017", 200, {"T02": None}, None, 1),
	"H10": ("Issue", "020", 180, {"V01": None, "M05": None, "K02": None, "T03": None}, None, 1),
	"H11": ("Issue", "019", 150, {"T04": None}, None, 1),
	# the Thevara test kit comes back in good condition and goes to Puliyanam
	"H12": ("Receipt", "008", 60, {"K01": "Good"}, "Thevara", 1),
	"H13": ("Issue", "009", 55, {"K01": None}, None, 1),
	# the service engineer returns a damaged tool kit (Asset Repair) and a good phone
	"H14": ("Receipt", "020", 30, {
		"T03": "Drill chuck is cracked and the second battery does not hold charge.",
		"M05": "Good",
	}, FACTORY, 1),
	# waiting for HR: a new laptop for the proposal engineer, saved but not submitted
	"H15": ("Issue", "010", 0, {"L07": None}, None, 0),
}
# The store keeper (T04 above) has resigned and leaves in a few days: Employee Asset Holdings
# (Leaving Only) and the exit reminders show the kit he still has to return.
LEAVING_EMPLOYEE = ("019", 25, 5)  # (employee no., resigned this many days ago, relieved in days)


# ======================================================================================= runner
def execute(company=None, run_setup=None):
	"""Load the demo data. run_setup: run the app's after_migrate setup first (default: only when the
	organisation structure is not there yet, e.g. a site where alantech_erp was just installed)."""
	company = company or _company()
	if not company:
		print("Demo data skipped: no Company yet (finish the setup wizard first).")
		return

	frappe.flags.mute_emails = True  # no welcome / workflow mails for demo users
	report = []
	if run_setup is None:
		run_setup = not _org_structure_ready()
	steps = [
		("Alantech setup (after_migrate hooks)", lambda: _run_app_setup() if run_setup else "already set up"),
		("Costing library", lambda: _costing_library()),
		("HR masters", lambda: _hr_masters(company)),
		("Payroll masters", lambda: _payroll_masters(company)),
		("CRM masters", lambda: _crm_masters()),
		("Items and prices", lambda: _items()),
		("Employees, users and sales persons", lambda: _employees(company)),
		("Leave policy assignments", lambda: _leave_assignments(company)),
		("Salary structure assignments", lambda: _salary_assignments(company)),
		("Shift assignments", lambda: _shift_assignments(company)),
		("Customers, contacts and addresses", lambda: _customers(company)),
		("Leads", lambda: _leads()),
		("Deals (Opportunities)", lambda: _deals(company)),
		("Quotation approval limit", lambda: _selling_settings()),
		("Asset masters (locations, categories, items)", lambda: _asset_masters(company)),
		("Assets", lambda: _assets(company)),
		("Employee asset handovers", lambda: _asset_handovers(company)),
		("Leaving employee with assets", lambda: _leaving_employee(company)),
	]
	for label, fn in steps:
		report.append(_step(label, fn))
	frappe.db.commit()
	frappe.flags.mute_emails = False

	print("\nAlantech demo data")
	for label, status in report:
		print(f"  {label}: {status}")
	print(f"\nDemo logins: <user>@{EMAIL_DOMAIN} / {_password()}  (e.g. sales.kerala@{EMAIL_DOMAIN})")
	return report


def _step(label, fn):
	"""Run one step in its own savepoint, so a failure in one master does not stop the rest."""
	savepoint = "alt_demo_" + re.sub(r"[^a-z0-9]+", "_", label.lower())[:40]
	frappe.db.savepoint(savepoint)
	try:
		result = fn()
		return label, result if isinstance(result, str) else "ok"
	except Exception:
		try:
			frappe.db.rollback(save_point=savepoint)
		except Exception:
			pass  # a setup function committed inside the step, which ends the savepoint
		frappe.log_error(title=f"Alantech demo data: {label}")
		return label, "FAILED (see Error Log)"


def _company():
	if frappe.db.exists("Company", ALANTECH_COMPANY):
		return ALANTECH_COMPANY
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def _password():
	return frappe.conf.get("alantech_demo_password") or DEMO_PASSWORD


def _email(user):
	return f"{user}@{EMAIL_DOMAIN}" if user else None


def _ensure(doctype, name, values=None, name_field=None):
	"""Insert a simple master if missing. name_field: the field autonamed from; else name is set."""
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.new_doc(doctype)
	if name_field:
		doc.set(name_field, name)
	else:
		doc.name = name
		doc.set("__newname", name)
	doc.update(values or {})
	doc.insert(ignore_permissions=True)
	return doc.name


def _has_field(doctype, fieldname):
	return frappe.get_meta(doctype).has_field(fieldname)


def _year_start(joining):
	start = getdate(f"{getdate(today()).year}-01-01")
	return max(start, getdate(joining))


# ======================================================================================= steps
def _org_structure_ready():
	return bool(
		frappe.get_meta("Designation").has_field("alt_role_profile")
		and frappe.db.get_value("Designation", "Sales Engineer", "alt_role_profile")
	)


# ------------------------------------------------------------------- migrate (patch + hook)
PENDING_KEY = "alantech_demo_data_pending"


def request_load():
	"""Called by the patch: load at the end of this migrate (after_migrate), once the app's own
	setup (roles, role profiles, departments, workflows) has run. Running that setup again inside the
	patch would save the Role Profiles twice in one migrate and hit their document lock."""
	frappe.db.set_default(PENDING_KEY, "1")


def after_migrate():
	"""Last after_migrate hook: load the demo data when the patch asked for it."""
	if not frappe.db.get_default(PENDING_KEY):
		return
	if not frappe.conf.get("alantech_demo_data"):
		return
	execute(run_setup=False)
	frappe.db.set_default(PENDING_KEY, None)
	frappe.db.commit()


def _run_app_setup():
	"""Roles, profiles, departments, designations, shifts, holiday lists, workflows, custom fields.

	These normally run after every migrate; during a migrate the patch runs before them, so run them
	here too (all of them are safe to re-run)."""
	for method in frappe.get_hooks("after_migrate", app_name="alantech_erp"):
		if method.endswith(("sales_person.execute", "demo.data.after_migrate")):
			continue  # employees come later in this run; never call ourselves
		frappe.get_attr(method)()


def _costing_library():
	if not frappe.db.exists("DocType", "Proposal Settings"):
		return "skipped"
	if frappe.db.get_single_value("Proposal Settings", "library_loaded"):
		return "already loaded"
	from alantech_erp.setup import proposal_library

	counts = proposal_library.load()
	return ", ".join(f"{k}: {v}" for k, v in counts.items())


def _hr_masters(company):
	for branch in BRANCHES:
		_ensure("Branch", branch, name_field="branch")
	for etype in EMPLOYMENT_TYPES:
		_ensure("Employment Type", etype, name_field="employee_type_name")
	for expense in EXPENSE_CLAIM_TYPES:
		_ensure("Expense Claim Type", expense, name_field="expense_type")

	gender_fields = _has_field("Leave Type", "alt_for_male")
	for leave_type, (max_days, carry, lwp, male, female) in LEAVE_TYPES.items():
		values = {"max_leaves_allowed": max_days, "is_carry_forward": carry, "is_lwp": lwp}
		if gender_fields:
			values.update({"alt_for_male": male, "alt_for_female": female})
		_ensure("Leave Type", leave_type, values, name_field="leave_type_name")

	if not frappe.db.exists("Leave Policy", {"title": LEAVE_POLICY, "docstatus": 1}):
		policy = frappe.get_doc(
			{
				"doctype": "Leave Policy",
				"title": LEAVE_POLICY,
				"leave_policy_details": [
					{"leave_type": lt, "annual_allocation": days} for lt, days in LEAVE_POLICY_DAYS.items()
				],
			}
		)
		policy.insert(ignore_permissions=True)
		policy.submit()


def _payroll_masters(company):
	for component, (abbr, ctype, formula, amount, payment_days) in SALARY_COMPONENTS.items():
		_ensure(
			"Salary Component",
			component,
			{"salary_component_abbr": abbr, "type": ctype, "depends_on_payment_days": payment_days},
			name_field="salary_component",
		)
		# an existing component not used anywhere yet: align it, or HRMS refuses the structure
		if frappe.db.get_value("Salary Component", component, "depends_on_payment_days") != payment_days and not (
			frappe.db.exists("Salary Detail", {"salary_component": component})
		):
			frappe.db.set_value("Salary Component", component, "depends_on_payment_days", payment_days)

	if frappe.db.exists("Salary Structure", SALARY_STRUCTURE):
		return "structure exists"
	rows = {"earnings": [], "deductions": []}
	for component, (abbr, ctype, formula, amount, payment_days) in SALARY_COMPONENTS.items():
		rows["earnings" if ctype == "Earning" else "deductions"].append(
			{
				"salary_component": component,
				"abbr": frappe.db.get_value("Salary Component", component, "salary_component_abbr") or abbr,
				"amount_based_on_formula": 1 if formula else 0,
				"formula": formula,
				"amount": amount,
				# per row as well: a component that already existed may say otherwise
				"depends_on_payment_days": payment_days,
			}
		)
	structure = frappe.get_doc(
		{
			"doctype": "Salary Structure",
			"name": SALARY_STRUCTURE,
			"__newname": SALARY_STRUCTURE,
			"company": company,
			"is_active": "Yes",
			"payroll_frequency": "Monthly",
			"currency": frappe.get_cached_value("Company", company, "default_currency"),
			**rows,
		}
	)
	structure.insert(ignore_permissions=True)
	structure.submit()


def _crm_masters():
	territory_root = get_root_of("Territory")
	for parent, children in TERRITORIES.items():
		if parent:
			_ensure("Territory", parent, {"parent_territory": territory_root, "is_group": 1}, "territory_name")
		for child in children:
			_ensure("Territory", child, {"parent_territory": parent or territory_root, "is_group": 0}, "territory_name")

	group_root = get_root_of("Customer Group")
	for group in CUSTOMER_GROUPS:
		_ensure("Customer Group", group, {"parent_customer_group": group_root, "is_group": 0}, "customer_group_name")

	for industry in INDUSTRIES:
		_ensure("Industry Type", industry, name_field="industry")

	# ERPNext v15+: the lead source is a UTM Source (older sites: Lead Source)
	for source in LEAD_SOURCES:
		if frappe.db.exists("DocType", "UTM Source"):
			_ensure("UTM Source", source)
		elif frappe.db.exists("DocType", "Lead Source"):
			_ensure("Lead Source", source, name_field="source_name")

	for otype in OPPORTUNITY_TYPES:
		_ensure("Opportunity Type", otype)
	for stage in SALES_STAGES:
		_ensure("Sales Stage", stage, name_field="stage_name")
	for reason in LOST_REASONS:
		_ensure("Opportunity Lost Reason", reason, name_field="lost_reason")


def _items():
	group_root = get_root_of("Item Group")
	for group in ITEM_GROUPS:
		_ensure("Item Group", group, {"parent_item_group": group_root, "is_group": 0}, "item_group_name")

	hsn_doctype = frappe.db.exists("DocType", "GST HSN Code")
	has_hsn_field = _has_field("Item", "gst_hsn_code")
	for code, (item_name, group, hsn, is_stock, rate) in ITEMS.items():
		if hsn_doctype:
			_ensure("GST HSN Code", hsn, {"description": HSN_DESCRIPTIONS.get(hsn)}, name_field="hsn_code")
		if not frappe.db.exists("Item", code):
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": item_name,
					"item_group": group,
					"stock_uom": "Nos",
					"is_stock_item": is_stock,
					"is_sales_item": 1,
					"include_item_in_manufacturing": 0,
					"description": item_name,
				}
			)
			if has_hsn_field:
				item.gst_hsn_code = hsn
			item.insert(ignore_permissions=True)
		price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"
		if frappe.db.exists("Price List", price_list) and not frappe.db.exists(
			"Item Price", {"item_code": code, "price_list": price_list}
		):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": rate}
			).insert(ignore_permissions=True)


def _employees(company):
	created = 0
	for number, first, last, gender, designation, branch, user, _base, _shift in EMPLOYEES:
		employee_number = EMP_PREFIX + number
		if frappe.db.exists("Employee", {"employee_number": employee_number, "company": company}):
			continue
		if not frappe.db.exists("Designation", designation):
			continue
		email = _email(user)
		emp = frappe.get_doc(
			{
				"doctype": "Employee",
				"employee_number": employee_number,
				"first_name": first,
				"last_name": last,
				"gender": gender,
				"date_of_birth": f"{1975 + int(number) % 20}-0{1 + int(number) % 9}-15",
				"date_of_joining": f"{2015 + int(number) % 9}-04-01",
				"company": company,
				"status": "Active",
				"designation": designation,
				"branch": branch,
				"employment_type": "Full-time",
				"cell_number": f"+91 98470 {int(number):05d}",
				"company_email": email,
				"prefered_contact_email": "Company Email" if email else "",
				# department, Reports To, approvers, user and role profile come from the Employee hooks
			}
		)
		emp.insert(ignore_permissions=True)
		created += 1
		if email and frappe.db.exists("User", email):
			from frappe.utils.password import update_password

			update_password(email, _password())
	return f"{created} created"


def _demo_employees(company):
	return frappe.get_all(
		"Employee",
		filters={"employee_number": ["like", f"{EMP_PREFIX}%"], "company": company, "status": "Active"},
		fields=["name", "employee_number", "date_of_joining"],
	)


def _by_number(company):
	return {e.employee_number: e for e in _demo_employees(company)}


def _leave_assignments(company):
	policy = frappe.db.get_value("Leave Policy", {"title": LEAVE_POLICY, "docstatus": 1}, "name")
	if not policy:
		return "skipped (no leave policy)"
	year_end = getdate(f"{getdate(today()).year}-12-31")
	created = 0
	for emp in _demo_employees(company):
		if frappe.db.exists("Leave Policy Assignment", {"employee": emp.name, "docstatus": 1}):
			continue
		assignment = frappe.get_doc(
			{
				"doctype": "Leave Policy Assignment",
				"employee": emp.name,
				"company": company,
				"leave_policy": policy,
				"effective_from": _year_start(emp.date_of_joining),
				"effective_to": year_end,
			}
		)
		assignment.insert(ignore_permissions=True)
		assignment.submit()
		created += 1
	return f"{created} created"


def _salary_assignments(company):
	if not frappe.db.get_value("Salary Structure", SALARY_STRUCTURE, "docstatus") == 1:
		return "skipped (no salary structure)"
	base_of = {EMP_PREFIX + row[0]: row[7] for row in EMPLOYEES}
	currency = frappe.get_cached_value("Company", company, "default_currency")
	created = 0
	for emp in _demo_employees(company):
		if frappe.db.exists("Salary Structure Assignment", {"employee": emp.name, "docstatus": 1}):
			continue
		ssa = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": emp.name,
				"salary_structure": SALARY_STRUCTURE,
				"company": company,
				"currency": currency,
				"from_date": _year_start(emp.date_of_joining),
				"base": base_of.get(emp.employee_number, 30000),
			}
		)
		ssa.insert(ignore_permissions=True)
		ssa.submit()
		created += 1
	return f"{created} created"


def _shift_assignments(company):
	employees = _by_number(company)
	created = 0
	for row in EMPLOYEES:
		shift, emp = row[8], employees.get(EMP_PREFIX + row[0])
		if not (shift and emp and frappe.db.exists("Shift Type", shift)):
			continue
		if frappe.db.exists("Shift Assignment", {"employee": emp.name, "shift_type": shift, "docstatus": 1}):
			continue
		assignment = frappe.get_doc(
			{
				"doctype": "Shift Assignment",
				"employee": emp.name,
				"shift_type": shift,
				"company": company,
				"start_date": _year_start(emp.date_of_joining),
				"status": "Active",
			}
		)
		assignment.insert(ignore_permissions=True)
		assignment.submit()
		created += 1
	return f"{created} created"


def _user_of(company, number):
	emp = _by_number(company).get(EMP_PREFIX + number)
	return frappe.db.get_value("Employee", emp.name, "user_id") if emp else None


def _sales_person_of(company, number):
	emp = _by_number(company).get(EMP_PREFIX + number)
	return frappe.db.get_value("Sales Person", {"employee": emp.name}, "name") if emp else None


def _customers(company):
	created = 0
	for name, (group, territory, industry, owner_no, contact, city, state, pincode) in CUSTOMERS.items():
		if frappe.db.exists("Customer", name):
			continue
		overseas = territory == "UAE"
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Company",
				"customer_group": group,
				"territory": territory,
				"industry": industry,
			}
		)
		if overseas and _has_field("Customer", "gst_category"):
			customer.gst_category = "Overseas"
		sales_person = _sales_person_of(company, owner_no)
		if sales_person:
			customer.append("sales_team", {"sales_person": sales_person, "allocated_percentage": 100})
		owner = _user_of(company, owner_no)
		if owner and _has_field("Customer", "account_manager"):
			customer.account_manager = owner
		customer.insert(ignore_permissions=True)
		_set_owner(customer, owner)

		first, last = contact
		slug = frappe.scrub(name.replace(DEMO_TAG, "")).strip("_").replace("_", "")[:20]
		email = f"{first.lower()}@{slug}.example"
		contact_doc = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first,
				"last_name": last,
				"designation": "Plant Head",
				"email_ids": [{"email_id": email, "is_primary": 1}],
				"phone_nos": [{"phone": "+971 50 000 0001" if overseas else "+91 94470 00001", "is_primary_mobile_no": 1}],
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		)
		contact_doc.insert(ignore_permissions=True)

		address = {
			"doctype": "Address",
			"address_title": name,
			"address_type": "Billing",
			"address_line1": "Plot 12, Industrial Estate",
			"city": city,
			"country": "United Arab Emirates" if overseas else "India",
			"is_primary_address": 1,
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
		}
		if state:
			address.update({"state": state, "pincode": pincode})
		if overseas and _has_field("Address", "gst_category"):
			address["gst_category"] = "Overseas"
		if frappe.db.exists("Country", address["country"]):
			frappe.get_doc(address).insert(ignore_permissions=True)

		customer.db_set({"customer_primary_contact": contact_doc.name}, update_modified=False)
		created += 1
	return f"{created} created"


def _set_owner(doc, user):
	"""Frappe always makes the session user (Administrator here) the owner on insert."""
	if user:
		doc.db_set("owner", user, update_modified=False)


def _source_field(doctype):
	if _has_field(doctype, "utm_source"):
		return "utm_source"
	return "source" if _has_field(doctype, "source") else None


def _leads():
	source_field = _source_field("Lead")
	company = _company()
	created = 0
	for idx, (first, last, company_name, industry, territory, source, status, owner_no) in enumerate(LEADS, 1):
		if frappe.db.exists("Lead", {"company_name": company_name}):
			continue
		owner = _user_of(company, owner_no)
		lead = frappe.get_doc(
			{
				"doctype": "Lead",
				"first_name": first,
				"last_name": last,
				"company_name": company_name,
				"email_id": f"{first.lower()}.{last.lower()}@lead-{idx}.example",
				"mobile_no": f"+91 90000 1000{idx}",
				"industry": industry,
				"territory": territory,
				"request_type": "Product Enquiry",
				"qualification_status": "In Process" if status in ("Replied", "Interested") else "Unqualified",
				"status": status,
				"lead_owner": owner,
			}
		)
		if source_field:
			lead.set(source_field, source)
		lead.insert(ignore_permissions=True)
		_set_owner(lead, owner)  # as if the salesperson made it
		created += 1
	return f"{created} created"


def _deals(company):
	source_field = _source_field("Opportunity")
	created = 0
	for opp_from, party, opp_type, stage, item_code, qty, owner_no, days in DEALS:
		party_name = party if opp_from == "Customer" else frappe.db.get_value("Lead", {"company_name": party}, "name")
		if not party_name or not frappe.db.exists(opp_from, party_name):
			continue
		if frappe.db.exists("Opportunity", {"opportunity_from": opp_from, "party_name": party_name}):
			continue
		rate = ITEMS[item_code][4]
		owner = _user_of(company, owner_no)
		values = {
			"doctype": "Opportunity",
			"opportunity_from": opp_from,
			"party_name": party_name,
			"company": company,
			"transaction_date": today(),
			"opportunity_type": opp_type,
			"sales_stage": stage,
			"expected_closing": add_days(today(), days),
			"probability": 50,
			"opportunity_owner": owner,
			"currency": frappe.get_cached_value("Company", company, "default_currency"),
			"opportunity_amount": rate * qty,
			"items": [
				{
					"item_code": item_code,
					"item_name": ITEMS[item_code][0],
					"qty": qty,
					"uom": "Nos",
					"rate": rate,
					"amount": rate * qty,
					"base_rate": rate,
					"base_amount": rate * qty,
				}
			],
		}
		if opp_from == "Customer":
			values["contact_person"] = frappe.db.get_value("Customer", party_name, "customer_primary_contact")
		opp = frappe.get_doc(values)
		if source_field:
			opp.set(source_field, "Existing Customer" if opp_from == "Customer" else "Referral")
		opp.insert(ignore_permissions=True)
		_set_owner(opp, owner)
		created += 1
	return f"{created} created"


def _selling_settings():
	from alantech_erp.sales import LEVEL_2_LIMIT_FIELD

	if not _has_field("Selling Settings", LEVEL_2_LIMIT_FIELD):
		return "skipped (sales flow fields missing)"
	if frappe.db.get_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD):
		return "kept existing limit"
	frappe.db.set_single_value("Selling Settings", LEVEL_2_LIMIT_FIELD, LEVEL_2_LIMIT)
	return f"Level 2 above {LEVEL_2_LIMIT:,}"


# ================================================================== assets and asset handover
def _asset_name(key):
	return f"{ASSETS[key][1]} {DEMO_TAG}"


def _asset_masters(company):
	if not frappe.db.exists("DocType", "Asset"):
		return "skipped (ERPNext Assets not installed)"

	for branch in BRANCHES:
		_ensure("Location", branch, name_field="location_name")

	ledgers = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": "Fixed Asset", "is_group": 0, "disabled": 0},
		fields=["name", "account_name"],
		order_by="lft asc",
	)
	if not ledgers:
		return "skipped (no Fixed Asset ledger in the chart of accounts)"
	accumulated = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Accumulated Depreciation", "is_group": 0}, "name")
	expense = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Depreciation", "is_group": 0}, "name")

	for category, hints in ASSET_CATEGORIES.items():
		if frappe.db.exists("Asset Category", category):
			continue
		ledger = next(
			(a.name for hint in hints for a in ledgers if hint.lower() in a.account_name.lower()),
			ledgers[0].name,
		)
		frappe.get_doc(
			{
				"doctype": "Asset Category",
				"asset_category_name": category,
				"accounts": [
					{
						"company_name": company,
						"fixed_asset_account": ledger,
						"accumulated_depreciation_account": accumulated,
						"depreciation_expense_account": expense,
					}
				],
			}
		).insert(ignore_permissions=True)

	_ensure("Item Group", ASSET_ITEM_GROUP,
	        {"parent_item_group": get_root_of("Item Group"), "is_group": 0}, "item_group_name")
	for code, (item_name, category) in ASSET_ITEMS.items():
		if frappe.db.exists("Item", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": item_name,
				"item_group": ASSET_ITEM_GROUP,
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_fixed_asset": 1,
				"asset_category": category,
				"is_sales_item": 0,
				"is_purchase_item": 1,
				"description": item_name,
			}
		).insert(ignore_permissions=True)


def _existing_asset_values():
	"""Assets already owned (no Purchase Receipt / Invoice). v16 has an Asset Type select,
	older versions an Is Existing Asset check."""
	meta = frappe.get_meta("Asset")
	values = {}
	if meta.has_field("asset_type"):
		options = (meta.get_field("asset_type").options or "").split("\n")
		existing = next((o for o in options if "Existing" in o), None)
		if existing:
			values["asset_type"] = existing
	if meta.has_field("is_existing_asset"):
		values["is_existing_asset"] = 1
	return values


def _assets(company):
	if not frappe.db.exists("DocType", "Asset"):
		return "skipped (ERPNext Assets not installed)"
	existing = _existing_asset_values()
	amount_fields = [f for f in ("net_purchase_amount", "gross_purchase_amount", "purchase_amount")
	                 if _has_field("Asset", f)]
	created, failed = 0, []
	for key, (item_code, _name, location, amount, days_ago) in ASSETS.items():
		asset_name = _asset_name(key)
		if frappe.db.exists("Asset", {"asset_name": asset_name, "company": company, "docstatus": ["<", 2]}):
			continue
		if not (frappe.db.get_value("Item", item_code, "is_fixed_asset") and frappe.db.exists("Location", location)):
			failed.append(key)
			continue
		bought = add_days(today(), -days_ago)
		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"company": company,
				"item_code": item_code,
				"asset_name": asset_name,
				"asset_category": frappe.db.get_value("Item", item_code, "asset_category"),
				"location": location,
				"asset_owner": "Company",
				"purchase_date": bought,
				"available_for_use_date": bought,
				"calculate_depreciation": 0,
				**existing,
				**{f: amount for f in amount_fields},
			}
		)
		savepoint = f"alt_demo_asset_{key.lower()}"
		frappe.db.savepoint(savepoint)
		try:
			asset.insert(ignore_permissions=True)
			asset.submit()   # ERPNext makes the first Asset Movement (Receipt to the location)
			created += 1
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(title=f"Alantech demo data: Asset {key}")
			failed.append(key)
	return f"{created} created" + (f", failed: {', '.join(failed)} (see Error Log)" if failed else "")


def _asset_handovers(company):
	if not frappe.db.exists("DocType", "Asset"):
		return "skipped (ERPNext Assets not installed)"
	employees = _by_number(company)
	assets = {}
	for key in ASSETS:
		name = frappe.db.get_value("Asset", {"asset_name": _asset_name(key), "company": company, "docstatus": 1}, "name")
		if name:
			assets[key] = name
	hr_manager = _user_of(company, "002")
	hr_executive = _user_of(company, "003")

	created, failed = 0, []
	for key, (ttype, number, days_ago, rows, location, submit) in HANDOVERS.items():
		tag = f"{DEMO_TAG} {key}:"
		if frappe.db.exists("Employee Asset Handover", {"remarks": ["like", f"{tag}%"], "docstatus": ["<", 2]}):
			continue
		emp = employees.get(EMP_PREFIX + number)
		if not emp or any(k not in assets for k in rows):
			failed.append(key)
			continue
		emp_info = frappe.db.get_value("Employee", emp.name, ["employee_name", "department"], as_dict=True)
		on = add_days(today(), -days_ago)
		inspected = ttype == "Receipt" and any(rows.values())
		names = ", ".join(ASSETS[k][1] for k in rows)
		doc = frappe.get_doc(
			{
				"doctype": "Employee Asset Handover",
				"transaction_type": ttype,
				"transaction_date": f"{on} 10:30:00",
				"employee": emp.name,
				"employee_name": emp_info.employee_name,
				"department": emp_info.department,
				"company": company,
				"location": location if ttype == "Receipt" else None,
				"inspection_required": 1 if inspected else 0,
				"inspected_by": hr_manager if inspected else None,
				"inspection_date": on if inspected else None,
				"inspection_remarks": "Checked at return against the issue list." if inspected else None,
				"remarks": f"{tag} {'Issued' if ttype == 'Issue' else 'Returned'}: {names}",
			}
		)
		for asset_key, condition in rows.items():
			row = {"asset": assets[asset_key]}
			if inspected and condition:
				row["condition"] = "Good" if condition == "Good" else "Damaged"
				if condition != "Good":
					row["issue_description"] = condition
			doc.append("items", row)

		savepoint = f"alt_demo_handover_{key.lower()}"
		frappe.db.savepoint(savepoint)
		try:
			doc.insert(ignore_permissions=True)
			if submit:
				doc.submit()   # Asset Movement, and Asset Repair for the damaged return
			_set_owner(doc, hr_executive)
			created += 1
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(title=f"Alantech demo data: Employee Asset Handover {key}")
			failed.append(key)
	return f"{created} created" + (f", failed: {', '.join(failed)} (see Error Log)" if failed else "")


def _leaving_employee(company):
	number, resigned_days_ago, relieved_in = LEAVING_EMPLOYEE
	emp = _by_number(company).get(EMP_PREFIX + number)
	if not emp:
		return "skipped (employee missing)"
	doc = frappe.get_doc("Employee", emp.name)
	if doc.relieving_date or doc.resignation_letter_date:
		return "already set"
	doc.resignation_letter_date = add_days(today(), -resigned_days_ago)
	doc.relieving_date = add_days(today(), relieved_in)
	doc.save(ignore_permissions=True)   # the exit alert tells HR which assets are still with him
	return f"{doc.employee_name} relieved on {doc.relieving_date}"

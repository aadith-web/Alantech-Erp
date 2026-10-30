"""Demo data for an Alantech demo / UAT site: users, employees, HRMS and CRM masters, sales persons,
customers, leads and deals, so every flow can be walked through as the right user.

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

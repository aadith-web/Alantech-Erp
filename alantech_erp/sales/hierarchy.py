"""Sales hierarchy: who sees which sales records and who approves a quotation.

The ERPNext Sales Person tree follows the sales line (built from Employee by sales_person.py):

    Sales Team (root)
    └── Sales Director                 (group)
        ├── Sales Manager              (group)
        │   ├── Sales Engineer
        │   └── Sales Engineer
        └── Sales Manager ...

Each Sales Person is linked to its user through the Employee record (Employee.user_id), so the
tree tells who sits under whom.

Access (Lead, Customer, Estimation, Technical Offer, Quotation, Deal, Sales Order):
    Sales Engineer   records they created, own or are assigned to
    Sales Manager    the same for themselves and everyone below them in the tree
    Sales Director   everything (top of the sales line), like any user outside the tree
                     (Management, Proposal Engineers, Sales Co-ordinator, Accounts...)
    System Manager   everything

Quotation approval (see sales/quotation.py):
    Level 1  the creator's own Sales Manager (nearest manager above them in the tree)
    Level 2  the Sales Director above them (value based, Selling Settings limit)
When a Sales Engineer moves teams, updating the tree moves their records and approvals with them.

hooks.py:
    permission_query_conditions = {<doctype>: "alantech_erp.sales.hierarchy.query_conditions"}
    has_permission = {<doctype>: "alantech_erp.sales.hierarchy.has_permission"}
"""

import json

import frappe
from frappe.utils.nestedset import get_ancestors_of, get_descendants_of

DIRECTOR_DESIGNATIONS = {"Sales Director", "Sales Head"}  # Sales Head: name used before Nov 2026
MANAGER_DESIGNATIONS = {"Sales Manager"}
ENGINEER_DESIGNATIONS = {"Sales Engineer"}

# Roles that always see every sales record
UNRESTRICTED_ROLES = {"System Manager", "Administrator"}

# Doctypes filtered by the hierarchy, with the user fields that also count as "theirs"
# (besides owner = created by, and _assign = assigned to)
USER_FIELDS = {
	"Lead": ("lead_owner",),
	"Customer": ("account_manager",),
	"Opportunity": ("opportunity_owner",),
	"Estimation": ("prepared_by", "sales_user"),
	"Technical Offer": ("sales_user",),
	"Quotation": ("alt_level_1_user", "alt_level_2_user"),  # the approvers named on it
	"Sales Order": (),
}


# ---------------------------------------------------------------------- request cache
_CACHE_KEYS = ("alt_sales_person_of_user", "alt_visible_users")


def _request_cache(key):
	"""A dict on frappe.local that lives for the current request.

	frappe.local has no __dict__ on v16 (custom Local in frappe/utils/local.py), so use
	getattr/setattr, which work on both the old Werkzeug Local and the new one.
	"""
	cache = getattr(frappe.local, key, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, key, cache)
	return cache


# ---------------------------------------------------------------------- tree lookups
def sales_person_of_user(user):
	"""The enabled Sales Person of the user's active Employee, with its designation (or None)."""
	if not user or user in ("Guest",):
		return None
	cache = _request_cache("alt_sales_person_of_user")
	if user in cache:
		return cache[user]
	row = None
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, ["name", "designation"], as_dict=True)
	if employee:
		name = frappe.db.get_value("Sales Person", {"employee": employee.name, "enabled": 1}, "name")
		if name:
			row = frappe._dict(name=name, employee=employee.name, designation=employee.designation, user=user)
	cache[user] = row
	return row


def _people(sales_persons):
	"""{sales person: _dict(user, designation, enabled)} for the given Sales Persons."""
	if not sales_persons:
		return {}
	rows = frappe.get_all(
		"Sales Person",
		filters={"name": ["in", list(sales_persons)]},
		fields=["name", "employee", "enabled"],
	)
	employees = {r.employee for r in rows if r.employee}
	emp = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", list(employees)]},
			fields=["name", "user_id", "designation", "status"],
		)
	} if employees else {}
	out = {}
	for r in rows:
		e = emp.get(r.employee) or frappe._dict()
		out[r.name] = frappe._dict(
			user=e.get("user_id"),
			designation=e.get("designation"),
			active=bool(r.enabled) and e.get("status") == "Active",
		)
	return out


def is_director(person):
	return bool(person) and person.designation in DIRECTOR_DESIGNATIONS


def is_unrestricted(user):
	if user == "Administrator":
		return True
	return bool(UNRESTRICTED_ROLES & set(frappe.get_roles(user)))


def visible_users(user=None):
	"""Users whose sales records `user` may see, or None when `user` sees everything.

	Restricted: users in the Sales Person tree below the Sales Director. They see their own
	records and those of everyone below them (disabled Sales Persons included, so a manager keeps
	the history of people who left the team).
	"""
	user = user or frappe.session.user
	cache = _request_cache("alt_visible_users")
	if user in cache:
		return cache[user]
	users = None
	if not is_unrestricted(user):
		person = sales_person_of_user(user)
		if person and not is_director(person):
			below = get_descendants_of("Sales Person", person.name, ignore_permissions=True)
			users = {user} | {p.user for p in _people(below).values() if p.user}
	cache[user] = users
	return users


def approvers_for(user):
	"""(Level 1 user, Level 2 user) for a quotation made by `user`, from the Sales Person tree.

	Level 1: the nearest Sales Manager (or Sales Director) above the user.
	Level 2: the Sales Director at the top of their line.
	Either is None when the tree has nobody there (the workflow then falls back to the role).
	"""
	person = sales_person_of_user(user)
	if not person:
		return None, None
	ancestors = get_ancestors_of("Sales Person", person.name)  # nearest first
	people = _people(ancestors)
	level_1 = level_2 = None
	for name in ancestors:
		p = people.get(name)
		if not p or not p.active or not p.user or p.user == user:
			continue
		if not level_1 and p.designation in MANAGER_DESIGNATIONS | DIRECTOR_DESIGNATIONS:
			level_1 = p.user
		if p.designation in DIRECTOR_DESIGNATIONS:
			level_2 = p.user  # keep going up: the top-most director wins
	if is_director(person):
		level_2 = None  # nobody above the director in sales; Level 2 falls back to the role
	return level_1, level_2


def clear_cache():
	for key in _CACHE_KEYS:
		setattr(frappe.local, key, {})


# ---------------------------------------------------------------------- permission hooks
def _user_conditions(doctype, users):
	table = f"`tab{doctype}`"
	values = ", ".join(frappe.db.escape(u) for u in sorted(users))
	conditions = [f"{table}.`owner` in ({values})"]
	meta = frappe.get_meta(doctype)
	for field in USER_FIELDS.get(doctype, ()):
		if meta.has_field(field):
			conditions.append(f"{table}.`{field}` in ({values})")
	for u in sorted(users):
		conditions.append(f"{table}.`_assign` like {frappe.db.escape('%' + json.dumps(u) + '%')}")
	return "(" + " or ".join(conditions) + ")"


def query_conditions(user=None, doctype=None):
	"""permission_query_conditions for the sales doctypes (one function, doctype from the hook)."""
	users = visible_users(user or frappe.session.user)
	if users is None or not doctype:
		return ""
	return _user_conditions(doctype, users)


def _make_query(doctype):
	def conditions(user=None, doctype=doctype):
		return query_conditions(user, doctype)

	return conditions


# Frappe passes only (user) to permission_query_conditions (and doctype on newer versions);
# one named function per doctype keeps it working on both.
lead_query = _make_query("Lead")
customer_query = _make_query("Customer")
opportunity_query = _make_query("Opportunity")
estimation_query = _make_query("Estimation")
technical_offer_query = _make_query("Technical Offer")
quotation_query = _make_query("Quotation")
sales_order_query = _make_query("Sales Order")


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Deny a record outside the user's part of the tree (role permissions still apply first)."""
	user = user or frappe.session.user
	if ptype == "create" or doc.is_new() or not doc.get("owner"):
		return True
	users = visible_users(user)
	if users is None:
		return True
	if doc.owner in users:
		return True
	for field in USER_FIELDS.get(doc.doctype, ()):
		if doc.get(field) in users:
			return True
	assigned = doc.get("_assign")
	if assigned:
		try:
			if users & set(json.loads(assigned)):
				return True
		except (TypeError, ValueError):
			pass
	return False

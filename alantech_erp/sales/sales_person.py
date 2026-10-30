"""Sales Person from Employee.

Every active employee in the Sales department (or a department under it) gets a Sales Person
linked to them, so they can be picked in the Sales Team of Customers, Quotations and Sales Orders
and show up in the sales person reports.

* Name: the employee name. If another Sales Person already has that name, "<name> - <employee ID>".
* Parent: the Sales Person of the employee's Reports To, when that manager is in Sales too;
  otherwise the root ("Sales Team").
* Sales Head and Sales Manager get a group Sales Person, so their team sits under them.
* Leaves Sales, or status no longer Active: the Sales Person is disabled, never deleted (old
  orders and targets still point at it). It is enabled again if the employee comes back.
* Employee deleted: the link is cleared so the delete is not blocked.

Values changed by hand on the Sales Person (parent, commission rate, targets) are kept; the parent
only follows the employee when their Reports To changes.

hooks.py:
    doc_events = {"Employee": {"on_update": [..., "alantech_erp.sales.sales_person.employee_on_update"],
                               "on_trash": "alantech_erp.sales.sales_person.employee_on_trash"}}
    after_migrate = [..., "alantech_erp.sales.sales_person.execute"]
"""

import frappe
from frappe import _
from frappe.utils.nestedset import get_ancestors_of, get_root_of

# Department names (Department.department_name, without the company suffix) whose employees sell
SALES_DEPARTMENTS = {"Sales"}

# Designations that lead a sales team: their Sales Person is a group, so others can sit under it
GROUP_DESIGNATIONS = {"Sales Head", "Sales Manager"}


# ---------------------------------------------------------------------- rules
def is_sales_department(department):
	"""True when the department, or one of its parents, is a Sales department."""
	if not department:
		return False
	names = [department, *get_ancestors_of("Department", department)]
	return any(
		frappe.db.get_value("Department", name, "department_name") in SALES_DEPARTMENTS for name in names
	)


def should_be_sales_person(emp):
	return emp.get("status") == "Active" and is_sales_department(emp.get("department"))


def sales_person_of(employee):
	return frappe.db.get_value("Sales Person", {"employee": employee}, "name") if employee else None


def root_sales_person():
	return get_root_of("Sales Person")


def parent_for(emp):
	"""The manager's Sales Person (made a group if needed), else the root."""
	manager_sp = sales_person_of(emp.get("reports_to"))
	if manager_sp and frappe.db.get_value("Sales Person", manager_sp, "enabled"):
		if not frappe.db.get_value("Sales Person", manager_sp, "is_group"):
			manager = frappe.get_doc("Sales Person", manager_sp)
			manager.is_group = 1
			manager.flags.ignore_permissions = True
			manager.save()
		return manager_sp
	return root_sales_person()


def unique_name(emp):
	name = (emp.get("employee_name") or emp.name).strip()
	owner = frappe.db.get_value("Sales Person", name, "employee")
	if frappe.db.exists("Sales Person", name) and owner != emp.name:
		name = f"{name} - {emp.name}"
	return name


# ---------------------------------------------------------------------- sync
def sync(emp, before=None):
	"""Create, update or disable the employee's Sales Person. Returns its name (or None)."""
	existing = sales_person_of(emp.name)

	if not should_be_sales_person(emp):
		if existing:
			_disable(existing, emp)
		return existing

	if not existing:
		sp = frappe.new_doc("Sales Person")
		sp.update(
			{
				"sales_person_name": unique_name(emp),
				"employee": emp.name,
				"department": emp.department,
				"is_group": 1 if emp.get("designation") in GROUP_DESIGNATIONS else 0,
				"parent_sales_person": parent_for(emp),
				"enabled": 1,
			}
		)
		sp.insert(ignore_permissions=True)
		frappe.msgprint(
			_("Sales Person {0} created for {1}.").format(frappe.bold(sp.name), emp.employee_name),
			indicator="green",
			alert=True,
		)
		return sp.name

	sp = frappe.get_doc("Sales Person", existing)
	fields = ("enabled", "department", "is_group", "parent_sales_person")
	old = {f: sp.get(f) for f in fields}
	sp.enabled = 1
	sp.department = emp.department
	if emp.get("designation") in GROUP_DESIGNATIONS:
		sp.is_group = 1  # never turned back off: it may already have a team under it
	if before is None or before.get("reports_to") != emp.get("reports_to") or not sp.parent_sales_person:
		parent = parent_for(emp)
		if parent != sp.name:
			sp.parent_sales_person = parent
	if any(sp.get(f) != old[f] for f in fields):
		sp.flags.ignore_permissions = True
		sp.save()
	return sp.name


def _disable(name, emp):
	if not frappe.db.get_value("Sales Person", name, "enabled"):
		return
	sp = frappe.get_doc("Sales Person", name)
	sp.enabled = 0
	sp.flags.ignore_permissions = True
	try:
		sp.save()
	except frappe.ValidationError:
		# ERPNext refuses while the Sales Person is in a Customer's Sales Team
		frappe.clear_last_message()
		frappe.msgprint(
			_("Sales Person {0} is still in the Sales Team of some Customers, so it was left enabled. "
			  "Replace it on those Customers, then disable it.").format(frappe.bold(name)),
			indicator="orange",
			alert=True,
		)
		return
	frappe.msgprint(
		_("Sales Person {0} disabled ({1} is no longer active in Sales).").format(frappe.bold(name), emp.employee_name),
		indicator="orange",
		alert=True,
	)


# ---------------------------------------------------------------------- Employee doc_events
def employee_on_update(doc, method=None):
	before = doc.get_doc_before_save()
	if before and all(
		before.get(f) == doc.get(f) for f in ("department", "status", "reports_to", "designation", "employee_name")
	) and (sales_person_of(doc.name) or not should_be_sales_person(doc)):
		return  # nothing that matters here changed
	sync(doc, before)


def employee_on_trash(doc, method=None):
	"""Clear the link so ERPNext's link check does not block deleting the employee."""
	name = sales_person_of(doc.name)
	if name:
		frappe.db.set_value("Sales Person", name, {"employee": None, "enabled": 0})


# ---------------------------------------------------------------------- after_migrate / one-off
def execute():
	"""Sales Persons for existing employees in Sales (managers first, so the tree builds top-down)."""
	if not frappe.db.exists("DocType", "Sales Person"):
		return
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", "department": ["is", "set"]},
		fields=["name", "department", "designation"],
		order_by="creation asc",
	)
	order = {d: i for i, d in enumerate(["Sales Head", "Sales Manager"])}
	employees.sort(key=lambda e: order.get(e.designation, len(order)))
	created = 0
	for row in employees:
		if not is_sales_department(row.department) or sales_person_of(row.name):
			continue
		sync(frappe.get_doc("Employee", row.name))
		created += 1
	if created:
		frappe.db.commit()
		print(f"Sales Person: created {created} from Sales employees.")

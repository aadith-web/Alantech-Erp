"""India Payroll on the Frappe HR rail.

India Payroll (frappe/india-payroll, installed 2026-11-19) is a companion app: no apps-screen tile
of its own, its module is meant to sit on the host app's rail (Frappe HR). Its version 16.2 still
ships the old `desktop_icon/` and `workspace_sidebar/` files, which this Frappe no longer imports,
and no `Dock` record that would mount it on Frappe HR, so it showed nowhere on the desk.

`execute` adds an "India Payroll" entry (module India Payroll, its sidebar computed from the
module's contents) to the site's arrangement of the Frappe HR rail. Same rule as
employee_grade.add_sub_band_to_sidebar: with no site arrangement yet, one is written that keeps
the HRMS rail and appends India Payroll; an existing arrangement only gets the entry appended; one
that already names India Payroll (also hidden by HR in Manage Dock) is left as it is.

Once India Payroll ships its own `Dock` mount, Frappe mounts it on the Frappe HR rail itself and
this entry merges with it (a dock entry is identified by its destination).

hooks.py: after_migrate.
"""

import frappe

HOST_APP = "hrms"
APP = "india_payroll"
MODULE = "India Payroll"
ENTRY = {"link_type": "Sidebar", "link_to": MODULE, "icon": "badge-indian-rupee", "title": "India Payroll"}


def execute():
	add_india_payroll_to_hr_rail()


def add_india_payroll_to_hr_rail():
	installed = frappe.get_installed_apps()
	if APP not in installed or HOST_APP not in installed or not frappe.db.exists("Module Def", MODULE):
		return
	from frappe.desk.doctype.dock.dock import get_site_dock, resolve_app_dock, save_site_dock

	site_rows = get_site_dock(HOST_APP)
	if any(row.get("link_type") == ENTRY["link_type"] and row.get("link_to") == MODULE for row in site_rows):
		return  # already arranged by the site (or hidden on purpose): leave it
	if site_rows:
		rows = [dict(row) for row in site_rows]
	else:
		# no site arrangement: start from the HRMS rail as it ships
		rows = [
			{"link_type": e.get("link_type"), "link_to": e.get("link_to"), "url": e.get("url")}
			for e in resolve_app_dock(HOST_APP, upto="app", gated=False)
		]
	save_site_dock(HOST_APP, rows + [dict(ENTRY)])

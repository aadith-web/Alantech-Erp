"""Demo data (users, employees, HRMS / CRM masters, sales persons, customers, leads, deals).

Only on demo / UAT sites: add "alantech_demo_data": 1 to the site's site_config.json (Frappe Cloud:
Site > Site Config) before `bench migrate`. On any other site this patch does nothing, so the live
company never gets demo records. Patches run once; to load the data later, or again after adding
the key, run:

    bench --site <site> execute alantech_erp.demo.data.execute
"""

import frappe


def execute():
	if not frappe.conf.get("alantech_demo_data"):
		print("alantech demo data: skipped (set alantech_demo_data = 1 in site_config.json to load it).")
		return

	# loaded by alantech_erp.demo.data.after_migrate, the last after_migrate hook
	from alantech_erp.demo import data

	data.request_load()
	print("alantech demo data: will load at the end of this migrate.")

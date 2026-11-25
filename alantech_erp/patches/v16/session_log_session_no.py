"""Session Logs made before IN-OUT sessions existed are Session 1 of their day."""

import frappe


def execute():
	frappe.db.sql("update `tabSession Log` set session_no = 1 where session_no is null or session_no = 0")
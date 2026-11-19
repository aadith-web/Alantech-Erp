import frappe

APP_NAME = "AlanTech"
APP_LOGO = "/assets/alantech_erp/images/alantech-logo.png"

# (doctype, fieldname, value). In Frappe v16:
#   - Website Settings app_name / app_logo  -> /login, /update-password, login emails
#   - Navbar Settings app_logo              -> brand logo on the apps screen (/desk)
#   - System Settings app_name              -> fallback app name
#   (favicon + splash image come from the website_context hook in hooks.py)
BRANDING = (
	("Website Settings", "app_name", APP_NAME),
	("Website Settings", "app_logo", APP_LOGO),
	("Navbar Settings", "app_logo", APP_LOGO),
	("System Settings", "app_name", APP_NAME),
)


def apply_branding():
	"""Set the Alantech name and logos used across login, desk and website.

	Runs after install and after every migrate; only writes values that differ, and
	skips any field a future Frappe version may drop.
	"""
	changed = False
	for doctype, fieldname, value in BRANDING:
		if not frappe.get_meta(doctype).has_field(fieldname):
			continue
		if frappe.db.get_single_value(doctype, fieldname) == value:
			continue
		frappe.db.set_single_value(doctype, fieldname, value)
		changed = True

	if changed:
		frappe.db.commit()
		frappe.clear_cache()
def _strip_chart_type(custom_options):
	import json

	if not custom_options:
		return custom_options, False
	try:
		options = json.loads(custom_options)
	except (TypeError, ValueError):
		return custom_options, False
	if not isinstance(options, dict) or "type" not in options:
		return custom_options, False
	options.pop("type")
	return (json.dumps(options) if options else None), True


def dashboard_chart_validate(doc, method=None):
	doc.custom_options, _ = _strip_chart_type(doc.get("custom_options"))


def fix_dashboard_chart_types():
	changed = False
	for name, custom_options in frappe.get_all(
		"Dashboard Chart", filters={"custom_options": ["is", "set"]}, fields=["name", "custom_options"], as_list=True
	):
		new_options, did_change = _strip_chart_type(custom_options)
		if did_change:
			frappe.db.set_value("Dashboard Chart", name, "custom_options", new_options, update_modified=False)
			changed = True
	if changed:
		frappe.db.commit()
		frappe.clear_cache()
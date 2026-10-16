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

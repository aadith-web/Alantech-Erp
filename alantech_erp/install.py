import frappe

APP_NAME = "AlanTech"
APP_LOGO = "/assets/alantech_erp/images/alantech-logo.png"


def apply_branding():
	"""Set the app name and logo used on /login and the desk navbar."""
	frappe.db.set_single_value("Website Settings", "app_name", APP_NAME)
	frappe.db.set_single_value("Website Settings", "app_logo", APP_LOGO)
	frappe.db.set_single_value("Navbar Settings", "app_logo", APP_LOGO)
	if frappe.get_meta("System Settings").has_field("app_name"):
		frappe.db.set_single_value("System Settings", "app_name", APP_NAME)
	frappe.db.commit()
	frappe.clear_cache()

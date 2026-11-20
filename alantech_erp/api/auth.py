import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils.password import check_password

BLOCKED_STATUSES = ("Inactive", "Left")


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=10, seconds=60)
def get_login_error_message(usr: str | None = None, pwd: str | None = None) -> str | None:
	if not usr or not pwd:
		return None

	user = frappe.db.get_value("User", {"name": usr}, "name") or frappe.db.get_value(
		"User", {"email": usr}, "name"
	)
	if not user:
		return _("Employee not found.")

	if frappe.db.exists("Employee", {"user_id": user, "status": ["in", BLOCKED_STATUSES]}):
		try:
			check_password(user, pwd, delete_tracker_cache=False)
		except Exception:
			return _("Incorrect password. Please try again.")
		return _("Your account is inactive. Please contact Administrator.")

	return _("Incorrect password. Please try again.")
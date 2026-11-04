"""Alert HR when a leaving employee still holds company assets.

- Employee on_update: when Resignation Letter Date or Relieving Date is set/changed, or Status
  becomes Left, and the employee is still Custodian of any asset.
- Employee Separation (HRMS) after_insert: same check when the exit process starts.
- Daily: reminder for employees relieved in the last 30 days or due within 7 days who still
  hold assets; it stops by itself once the assets are received back.

Recipients: every enabled HR Manager (bell notification, plus email when outgoing email is set up).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cstr, formatdate, get_link_to_form, getdate, today

from alantech_erp.alantech.doctype.document.document import get_hr_managers, send_notification
from alantech_erp.alantech.doctype.employee_asset_handover.employee_asset_handover import get_assets_held

EXIT_FIELDS = ("resignation_letter_date", "relieving_date")
REMIND_DAYS_BEFORE = 7
REMIND_DAYS_AFTER = 30


def employee_on_update(doc, method=None):
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [f for f in EXIT_FIELDS if doc.get(f) and cstr(doc.get(f)) != cstr(before.get(f))]
	became_left = doc.status == "Left" and before.status != "Left"
	if changed or became_left:
		alert_assets_not_returned(doc, show_message=True)


def employee_separation_after_insert(doc, method=None):
	if doc.get("employee"):
		alert_assets_not_returned(frappe.get_doc("Employee", doc.employee), show_message=True)


def send_daily_reminders():
	start, end = add_days(today(), -REMIND_DAYS_AFTER), add_days(today(), REMIND_DAYS_BEFORE)
	employees = frappe.get_all("Employee", filters={"relieving_date": ["between", [start, end]]}, pluck="name")
	for name in employees:
		alert_assets_not_returned(frappe.get_doc("Employee", name))


def alert_assets_not_returned(employee, show_message=False):
	assets = get_assets_held(employee.name)
	if not assets:
		return

	who = f"{employee.employee_name} ({employee.name})"
	when = ""
	if employee.relieving_date:
		days = (getdate(employee.relieving_date) - getdate(today())).days
		when = (_("was relieved on {0}") if days < 0 else _("is relieved on {0}")).format(
			formatdate(employee.relieving_date))
	elif employee.status == "Left":
		when = _("has left")
	else:
		when = _("has resigned")

	subject = _("Assets not returned: {0} {1} and still holds {2} asset(s)").format(who, when, len(assets))
	lines = "<br>".join(
		f"&bull; {get_link_to_form('Asset', a.asset)} &ndash; {frappe.utils.escape_html(a.asset_name or '')}"
		for a in assets)
	message = _("{0} {1}. These assets are still issued to the employee:").format(who, when) + "<br>" + lines \
		+ "<br><br>" + _("Receive them with an Employee Asset Handover (Type: Receipt) before the Full and Final Statement.")

	send_notification(get_hr_managers(), subject, message, employee)

	if show_message:
		frappe.msgprint(message, title=_("Assets Not Returned"), indicator="orange")

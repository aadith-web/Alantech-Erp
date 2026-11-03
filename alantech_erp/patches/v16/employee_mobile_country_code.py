import frappe
import phonenumbers

from alantech_erp.setup.employee_validation import format_mobile_number


def execute():
	"""Mobile became a Phone field with a country code (+971-501234567). Older numbers without
	one get the code of the default country (System Settings); numbers that still are not valid
	are left as they are, to be corrected on the Employee."""
	country = frappe.db.get_default("country")
	region = (frappe.db.get_value("Country", country, "code") or "").upper() or None
	for name, mobile in frappe.get_all("Employee", filters={"cell_number": ["is", "set"]}, fields=["name", "cell_number"], as_list=True):
		try:
			number = phonenumbers.parse(mobile.strip(), None if mobile.strip().startswith("+") else region)
		except phonenumbers.NumberParseException:
			continue
		if not phonenumbers.is_valid_number(number):
			continue
		formatted = format_mobile_number(number)
		if formatted != mobile:
			frappe.db.set_value("Employee", name, "cell_number", formatted, update_modified=False)

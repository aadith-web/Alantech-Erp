"""Setup for costing and technical offers (runs after every `bench migrate`, see hooks.py).

* Letter Head "Alantech" (logo + address, email footer) for the proposal print formats
* Proposal Settings: the Alantech letter head on first setup
* The standard water treatment library is loaded once (Proposal Settings > Load Standard Library
  adds anything missing later)

Safe to re-run: existing records are never overwritten.
"""

import frappe

LETTER_HEAD = "Alantech"

HEADER = """<table style="width: 100%; border-collapse: collapse;">
<tr>
	<td style="width: 45%; vertical-align: top;">
		<img src="/assets/alantech_erp/images/alantech-logo.png" alt="Alantech" style="height: 72px;">
	</td>
	<td style="text-align: right; vertical-align: top; line-height: 1.7;">
		<div style="font-size: 15pt; color: #1c7396;">Alantech Industries India Pvt Ltd</div>
		<div style="font-size: 9.5pt; color: #46a336;">9/581, Putthusery Bld, Mookkanoor,<br>Kochi, Kerala, India<br>+91 6235062300 &nbsp;|&nbsp; www.alantech.in</div>
	</td>
</tr>
</table>"""

FOOTER = """<div style="text-align: center; font-size: 8pt; color: #5fa8d3;">
Email : purchase@alantech.in, sales@alantech.in, finance@alantech.in
</div>"""


def execute():
	if not frappe.db.exists("DocType", "Quotation"):
		return  # ERPNext not installed on this site

	create_letter_head()
	if not frappe.db.get_single_value("Proposal Settings", "library_loaded"):
		# first setup: proposals use the Alantech letter head (a new single doc would
		# otherwise pick up the site's default letter head)
		if frappe.db.exists("Letter Head", LETTER_HEAD):
			frappe.db.set_single_value("Proposal Settings", "letter_head", LETTER_HEAD)
		from alantech_erp.setup.proposal_library import load

		load()
	frappe.db.commit()


def create_letter_head():
	if frappe.db.exists("Letter Head", LETTER_HEAD):
		return
	frappe.get_doc(
		{
			"doctype": "Letter Head",
			"letter_head_name": LETTER_HEAD,
			"source": "HTML",
			"content": HEADER,
			"footer_source": "HTML",
			"footer": FOOTER,
			"is_default": 0 if frappe.db.exists("Letter Head", {"is_default": 1}) else 1,
		}
	).insert(ignore_permissions=True)

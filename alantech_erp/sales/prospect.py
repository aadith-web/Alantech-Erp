"""The ERPNext Prospect flow is not used by Alantech.

A verified Lead becomes a Customer (Company or Individual) and the Deal is made from the
Quotation, so nothing creates or links a Prospect:
  * Lead: no Create > Prospect / Action > Add to Prospect / Create > Opportunity (public/js/lead.js),
    no Prospect on its dashboard (sales/dashboards.py lead)
  * Opportunity and Quotation: Prospect is not offered as the party type and is refused on save
    (sales/deal.py validate_opportunity, sales/quotation.py validate)
  * Customer: the "From Prospect" field is hidden (setup/sales_flow.py)
  * Prospect: new ones are refused here; the doctype is left to System Managers
    (Custom DocPerm, setup/sales_flow.py) so existing records stay readable but leave the menus.
"""

import frappe
from frappe import _


def before_insert(doc, method=None):
	frappe.throw(
		_("Prospects are not used. Convert the Lead to a Customer (Company or Individual) instead."),
		title=_("Prospect Not Used"),
	)

"""Doctype dashboard overrides for the sales doctypes (override_doctype_dashboards in hooks.py).

The Employee override lives in alantech_erp/alantech/dashboards.py.
"""

from frappe import _


def _add_activities(data, doctype):
	"""Sales Activities (CRM C10) on the Connections of a Lead / Customer / Deal: they link to the
	record by reference_doctype + reference_name."""
	transactions = data.setdefault("transactions", [])
	if not any("Sales Activity" in group.get("items", []) for group in transactions):
		transactions.insert(0, {"label": _("Activities"), "items": ["Sales Activity"]})
	data.setdefault("non_standard_fieldnames", {})["Sales Activity"] = "reference_name"
	data.setdefault("dynamic_links", {})["reference_name"] = [doctype, "reference_doctype"]
	return data


def customer(data):
	"""Customer dashboard: its Estimations and Technical Offers next to Deals and Quotations."""
	_add_activities(data, "Customer")
	for group in data.get("transactions", []):
		if "Quotation" in group.get("items", []):
			pos = group["items"].index("Quotation")
			for doctype in ("Technical Offer", "Estimation"):
				if doctype not in group["items"]:
					group["items"].insert(pos, doctype)
			return data
	data.setdefault("transactions", []).insert(0, {"label": "Pre Sales", "items": ["Estimation", "Technical Offer"]})
	return data


def lead(data):
	"""Lead dashboard: no Prospect (the Prospect flow is not used; a Lead becomes a Customer)."""
	_add_activities(data, "Lead")
	for group in data.get("transactions", []):
		group["items"] = [item for item in group.get("items", []) if item != "Prospect"]
	data["transactions"] = [group for group in data.get("transactions", []) if group.get("items")]
	return data


def opportunity(data):
	"""Deal dashboard: its Sales Activities."""
	return _add_activities(data, "Opportunity")


def campaign(data):
	"""Campaign Connections: its child campaigns (Campaign.alt_parent_campaign).

	The Leads, Deals, Quotations and Sales Orders link to the campaign's UTM Campaign, not to the
	Campaign itself, so they are opened from the form's View buttons (public/js/campaign.js)."""
	transactions = data.setdefault("transactions", [])
	if not any("Campaign" in group.get("items", []) for group in transactions):
		transactions.append({"label": _("Child Campaigns"), "items": ["Campaign"]})
	data.setdefault("non_standard_fieldnames", {})["Campaign"] = "alt_parent_campaign"
	data.setdefault("fieldname", "alt_parent_campaign")
	return data

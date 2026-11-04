"""Doctype dashboard overrides (override_doctype_dashboards in hooks.py)."""


def customer(data):
	"""Customer dashboard: its Estimations and Technical Offers next to Deals and Quotations."""
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
	for group in data.get("transactions", []):
		group["items"] = [item for item in group.get("items", []) if item != "Prospect"]
	data["transactions"] = [group for group in data.get("transactions", []) if group.get("items")]
	return data

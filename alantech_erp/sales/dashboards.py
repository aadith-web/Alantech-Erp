"""Doctype dashboard overrides (override_doctype_dashboards in hooks.py)."""


def opportunity(data):
	"""Show Estimations and Technical Offers in the Deal's Connections, before Quotations."""
	for group in data.get("transactions", []):
		if "Quotation" in group.get("items", []):
			for pos, doctype in enumerate(("Estimation", "Technical Offer")):
				if doctype not in group["items"]:
					group["items"].insert(pos, doctype)
			return data
	data.setdefault("transactions", []).insert(0, {"items": ["Estimation", "Technical Offer"]})
	return data

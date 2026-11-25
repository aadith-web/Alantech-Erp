# Copyright (c) 2026, JincyTricta and contributors
# For license information, please see license.txt
"""Asset Warranty picked as years / months, and Warranty Expiry Date calculated from it
(ClickUp 14yr2e58k7e follow-up). Fields: setup/asset_handover.py (ASSET_WARRANTY_FIELDS).

- Warranty (Years) 1-30 and Warranty (Months) 1-11 are dropdowns; Warranty (read-only text, used
  by the handover rows) shows the period: "2 Years", "6 Months", "1 Year 6 Months".
- Data Import / API may still send only a Warranty text ("2 years", "1 yr 6 mos", "2y 6m"): it is
  read into the years / months; any other text is refused.
- Warranty Expiry Date = Purchase Date + the period (e.g. 01-11-2026 + 2 Years = 01-11-2028); it is
  read-only while a period is picked. Without one the date can still be typed in.
- Recalculated whenever the Warranty or the Purchase Date changes, also on a submitted Asset
  (both warranty fields can be changed after submit).

Hooked: Asset validate and before_update_after_submit (hooks.py); the form does the same at once
(public/js/asset.js).
"""

import re

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate

WARRANTY = "alt_warranty"
YEARS, MONTHS = "alt_warranty_years", "alt_warranty_months"
EXPIRY = "alt_warranty_expiry_date"
MAX_MONTHS = 30 * 12

PATTERN = re.compile(
	r"^\s*(?:(?P<years>\d+)\s*(?:years?|yrs?|y)\b)?\s*(?:,|and|&)?\s*(?:(?P<months>\d+)\s*(?:months?|mons?|mos?|mths?|m)\b)?\s*$",
	re.IGNORECASE,
)


class WarrantyError(frappe.ValidationError):
	pass


def parse(text):
	"""(years, months) of a warranty text, or None when it is not a period."""
	match = PATTERN.match(text or "")
	if not match or not (match.group("years") or match.group("months")):
		return None
	years, months = int(match.group("years") or 0), int(match.group("months") or 0)
	if years * 12 + months <= 0:
		return None
	return years, months


def label(years, months):
	parts = []
	if years:
		parts.append(f"{years} Year" + ("s" if years != 1 else ""))
	if months:
		parts.append(f"{months} Month" + ("s" if months != 1 else ""))
	return " ".join(parts)


def expiry(purchase_date, years, months):
	return getdate(add_months(getdate(purchase_date), years * 12 + months)) if purchase_date else None


def picked(doc):
	"""(years, months) from the dropdowns, else from a Warranty text (import / API), else None."""
	years, months = cint(doc.get(YEARS)), cint(doc.get(MONTHS))
	if years or months:
		return years, months
	text = (doc.get(WARRANTY) or "").strip()
	if not text or not doc.is_new() and not doc.has_value_changed(WARRANTY):
		return None  # dropdowns cleared on the form: no warranty
	period = parse(text)
	if not period:
		frappe.throw(
			_("Warranty must be a period in years and / or months, e.g. 2 Years, 6 Months or 1 Year 6 Months (not \"{0}\").").format(text),
			WarrantyError, title=_("Invalid Warranty"))
	return period


def validate(doc, method=None):
	period = picked(doc)
	if not period:
		doc.update({WARRANTY: None, YEARS: None, MONTHS: None})
		return
	years, months = period
	if months > 11:
		years, months = years + months // 12, months % 12
	if years * 12 + months > MAX_MONTHS:
		frappe.throw(_("Warranty cannot be longer than 30 years."), WarrantyError, title=_("Invalid Warranty"))
	doc.update({WARRANTY: label(years, months), YEARS: str(years) if years else None,
		MONTHS: str(months) if months else None})
	if doc.get("purchase_date"):
		doc.set(EXPIRY, expiry(doc.purchase_date, years, months))

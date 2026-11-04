"""Document numbers: format check per Document Type Master (Number Format), and one document per
number within a type. Used by Document.validate and, while typing, by document.js."""

import re

import frappe
from frappe import _
from stdnum import luhn, verhoeff

CUSTOM = "Custom Pattern"


# check digits from python-stdnum (tested implementations; a hand-typed table got one row wrong)
def verhoeff_ok(digits):
	"""Aadhaar: the last digit is a Verhoeff check digit (UIDAI)."""
	return verhoeff.is_valid(digits)


def luhn_ok(digits):
	"""Emirates ID: the last digit is a Luhn check digit."""
	return luhn.is_valid(digits)


def _compact(value):
	"""Upper case, without spaces, dashes, dots or slashes."""
	return re.sub(r"[\s\-./]", "", value).upper()


# format -> pattern on the compact value, extra check, how it is stored, example
FORMATS = {
	"Aadhaar": {
		"pattern": r"[2-9][0-9]{11}",
		"check": verhoeff_ok,
		"display": lambda v: f"{v[:4]} {v[4:8]} {v[8:]}",
		"example": "2345 6789 0124",
	},
	"PAN": {
		# 4th letter: holder type (P person, C company, H HUF, F firm, ...)
		"pattern": r"[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]",
		"example": "ABCPE1234F",
	},
	"Indian Passport": {
		"pattern": r"[A-Z][1-9][0-9]{6}",
		"example": "A1234567",
	},
	"Indian Driving Licence": {
		# state code, RTO code, year of issue, serial number
		"pattern": r"[A-Z]{2}[0-9]{2}(19|20)[0-9]{2}[0-9]{7}",
		"display": lambda v: f"{v[:4]} {v[4:]}",
		"example": "KL07 20110012345",
	},
	"Emirates ID": {
		"pattern": r"784(19|20)[0-9]{2}[0-9]{8}",
		"check": luhn_ok,
		"display": lambda v: f"{v[:3]}-{v[3:7]}-{v[7:14]}-{v[14:]}",
		"example": "784-1990-1234567-6",
	},
}

FORMAT_OPTIONS = ["", *FORMATS, CUSTOM]


def get_rules(document_type):
	return frappe.db.get_value(
		"Document Type Master",
		document_type,
		["number_format", "number_pattern", "number_example", "number_mandatory"],
		as_dict=True,
	) or frappe._dict()


def example_for(rules):
	return rules.get("number_example") or FORMATS.get(rules.get("number_format"), {}).get("example")


def clean_number(document_type, number, rules=None):
	"""(value to store, error or None). Known formats are stored in one way (e.g. Aadhaar
	"2345 6789 0124"), so the duplicate check finds the same number however it was typed."""
	rules = rules or get_rules(document_type)
	number = re.sub(r"\s+", " ", (number or "").strip())
	if not number:
		return number, None
	fmt = rules.get("number_format")
	if fmt in FORMATS:
		spec = FORMATS[fmt]
		value = _compact(number)
		if re.fullmatch(spec["pattern"], value):
			if spec.get("check", lambda v: True)(value):
				return spec.get("display", lambda v: v)(value), None
			# right shape, but the check digit does not match the other digits
			return number, _(
				"{0} is not a valid {1} number: the check digit does not match. "
				"A digit is probably mistyped; compare it with the card."
			).format(frappe.bold(number), document_type)
	elif fmt == CUSTOM and rules.get("number_pattern"):
		if re.fullmatch(rules.number_pattern, number):
			return number, None
	else:
		return number, None
	example = example_for(rules)
	if example:
		return number, _("{0} is not a valid {1} number. It should look like {2}.").format(
			frappe.bold(number), document_type, frappe.bold(example)
		)
	return number, _("{0} is not a valid {1} number.").format(frappe.bold(number), document_type)


def find_duplicate(document_type, number, name=None):
	return frappe.db.get_value(
		"Document",
		{"document_type": document_type, "card_number": number, "name": ["!=", name or ""]},
		["name", "reference_title"],
		as_dict=True,
	)


def validate_document_number(doc):
	"""Document.validate: format, mandatory and duplicate checks for card_number."""
	rules = get_rules(doc.document_type)
	label = _("{0} Number").format(doc.document_type)
	doc.card_number, error = clean_number(doc.document_type, doc.card_number, rules)
	if error:
		frappe.throw(error, title=_("Invalid {0}").format(label))
	if not doc.card_number:
		if rules.get("number_mandatory"):
			frappe.throw(_("{0} is mandatory.").format(label), frappe.MandatoryError, title=_("Missing {0}").format(label))
		return
	duplicate = find_duplicate(doc.document_type, doc.card_number, doc.name)
	if duplicate:
		frappe.throw(
			_("{0} {1} is already on {2} ({3}).").format(
				label, frappe.bold(doc.card_number), duplicate.name, duplicate.reference_title
			),
			frappe.DuplicateEntryError,
			title=_("Duplicate {0}").format(label),
		)


@frappe.whitelist()
def check_number(document_type: str, number: str | None = None, name: str | None = None) -> dict:
	"""For the form: the number as it will be stored, any error, and the example to show."""
	frappe.has_permission("Document", "read", throw=True)
	rules = get_rules(document_type)
	value, error = clean_number(document_type, number, rules)
	if value and not error:
		duplicate = find_duplicate(document_type, value, name)
		if duplicate:
			error = _("{0} Number {1} is already on {2} ({3}).").format(
				document_type, frappe.bold(value), duplicate.name, duplicate.reference_title
			)
	return {"value": value, "error": error, "example": example_for(rules), "mandatory": rules.get("number_mandatory")}


def validate_pattern(pattern):
	"""Document Type Master.validate: a custom pattern must be a valid regular expression."""
	try:
		re.compile(pattern)
	except re.error as e:
		frappe.throw(_("Number Pattern is not a valid regular expression: {0}").format(e), title=_("Invalid Pattern"))

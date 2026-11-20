"""Document numbers: format check per Document Type Master (Number Format), and one document per
number within a type. Used by Document.validate and, while typing, by document.js.

Duplicates (ClickUp 14yr2e57c6k): an identity number (Aadhaar, Passport, Driving Licence, ...)
belongs to one person, so the same number is refused for any other employee or record, and twice
for the same one. Numbers are compared by number_key (upper case, no spaces / dashes / dots /
slashes), so "DL-TEST-123456", "dl test 123456" and "DL/TEST/123456" are the same number even for a
type without a Number Format. Rejected documents do not count. Users without HR access are not told
whose number it is."""

import re

import frappe
from frappe import _
from frappe.utils import cint
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
		["number_required", "number_format", "number_pattern", "number_example", "number_mandatory"],
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


REJECTED = "Rejected"


def number_key(number):
	"""What two numbers are compared by: upper case, no spaces, dashes, dots or slashes."""
	return _compact(number) if number and number.strip() else None


def find_duplicate(document_type, number, name=None):
	"""Another non-rejected document of this type with the same number (however it was typed)."""
	key = number_key(number)
	if not key:
		return None
	return frappe.db.get_value(
		"Document",
		{
			"document_type": document_type,
			"number_key": key,
			"name": ["!=", name or ""],
			"approval_status": ["!=", REJECTED],
		},
		["name", "reference_doctype", "reference_name", "reference_title", "employee"],
		as_dict=True,
		order_by="creation asc",
	)


def duplicate_message(document_type, number, duplicate, reference_doctype=None, reference_name=None):
	"""'Driving License Number DL-TEST-123456 already exists for another employee. Duplicate not
	allowed.' HR also sees whose document it is; an employee is not told whose number it is."""
	label = _("{0} Number {1}").format(document_type, frappe.bold(number))
	same_record = duplicate.reference_doctype == reference_doctype and duplicate.reference_name == reference_name
	if same_record:
		owner = _("this employee") if duplicate.employee else _("this record")
	else:
		owner = _("another employee") if duplicate.employee else _("another record")
	message = _("{0} already exists for {1}. Duplicate not allowed.").format(label, owner)

	from alantech_erp.alantech.doctype.document.document import has_unrestricted_role

	if same_record or has_unrestricted_role():
		message += " " + _("See {0} ({1}).").format(
			frappe.utils.get_link_to_form("Document", duplicate.name), duplicate.reference_title
		)
	return message


def validate_document_number(doc):
	"""Document.validate: format, mandatory and duplicate checks for card_number. A type without
	"Show Number" has no Number field: nothing is required (a number saved earlier is kept)."""
	rules = get_rules(doc.document_type)
	doc.number_required = cint(rules.get("number_required"))
	if not doc.number_required:
		rules.number_mandatory = 0
	label = _("{0} Number").format(doc.document_type)
	doc.card_number, error = clean_number(doc.document_type, doc.card_number, rules)
	doc.number_key = number_key(doc.card_number)
	if error:
		frappe.throw(error, title=_("Invalid {0}").format(label))
	if not doc.card_number:
		if rules.get("number_mandatory"):
			frappe.throw(_("{0} is mandatory.").format(label), frappe.MandatoryError, title=_("Missing {0}").format(label))
		return
	duplicate = find_duplicate(doc.document_type, doc.card_number, doc.name)
	if duplicate:
		frappe.throw(
			duplicate_message(doc.document_type, doc.card_number, duplicate, doc.reference_doctype, doc.reference_name),
			frappe.DuplicateEntryError,
			title=_("Duplicate {0}").format(label),
		)


@frappe.whitelist()
def check_number(
	document_type: str,
	number: str | None = None,
	name: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	"""For the form: the number as it will be stored, any error, and the example to show."""
	frappe.has_permission("Document", "read", throw=True)
	rules = get_rules(document_type)
	value, error = clean_number(document_type, number, rules)
	if value and not error:
		duplicate = find_duplicate(document_type, value, name)
		if duplicate:
			error = duplicate_message(document_type, value, duplicate, reference_doctype, reference_name)
	return {
		"value": value,
		"error": error,
		"example": example_for(rules),
		"required": cint(rules.get("number_required")),
		"mandatory": cint(rules.get("number_required")) and cint(rules.get("number_mandatory")),
		"rules": live_rules(rules),
	}


def live_rules(rules):
	"""Pattern and check digit for document.js, which checks the number on every key press
	(same rules as clean_number; the server still checks again on save)."""
	fmt = rules.get("number_format")
	if fmt in FORMATS:
		spec = FORMATS[fmt]
		check_digit = {verhoeff_ok: "verhoeff", luhn_ok: "luhn"}.get(spec.get("check"))
		return {"pattern": spec["pattern"], "compact": 1, "check_digit": check_digit}
	if fmt == CUSTOM and rules.get("number_pattern"):
		return {"pattern": rules.number_pattern, "compact": 0}
	return {}


def validate_pattern(pattern):
	"""Document Type Master.validate: a custom pattern must be a valid regular expression."""
	try:
		re.compile(pattern)
	except re.error as e:
		frappe.throw(_("Number Pattern is not a valid regular expression: {0}").format(e), title=_("Invalid Pattern"))

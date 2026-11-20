"""Employee bank and statutory number formats (Salary tab: India Payroll and Bank Details sections).

Checked on Employee.validate for new employees and new / changed values only, so an older malformed
value does not block system saves (promotion, transfer, user linking). All invalid fields are
reported in one message. Values are normalised first (trimmed; codes upper-cased; spaces removed
from numbers). PAN is checked by employee_nationality.validate_indian_ids.

- UAN: 12 digits (EPFO).
- Name as per UAN, Account Holder Name: letters, spaces, dot, apostrophe, hyphen.
- ESIC IP Number: 10 digits.
- IFSC Code (both fields: HRMS ifsc_code and alt_ifsc_code): 4 letters, 0, 6 letters/digits,
  e.g. SBIN0001234.
- MICR Code: 9 digits.
- Provident Fund Account: letters, digits and "/" (e.g. MHBAN00000640000000125 or
  KN/BNG/12345/000/1234567), 5 to 30 characters.
- Bank A/C No.: 9 to 18 digits.
- Bank Name, Bank Branch: letters, digits, spaces and . , & ' ( ) - /, with at least one letter.
- IBAN: country code, 2 check digits, 11 to 30 letters/digits, valid ISO 13616 (mod 97) checksum.

The form shows the same messages as soon as a value is entered (public/js/employee.js,
ALT_BANK_RULES); hooked in hooks.py: Employee validate.
"""

import re

import frappe
from frappe import _

NAME = r"[A-Za-z][A-Za-z .'\-]*"
BANK_TEXT = r"(?=.*[A-Za-z])[A-Za-z0-9 .,&'()\-/]+"

# fieldname: (normalise, pattern, message); messages translated when shown
UPPER = "upper"  # trim + upper-case
COMPACT = "compact"  # trim + upper-case + no spaces
TRIM = "trim"

RULES = {
    "uan_number": (COMPACT, r"[0-9]{12}", "must be 12 digits"),
    "pf_name": (TRIM, NAME, "may contain only letters, spaces, dot, apostrophe and hyphen"),
    "esic_card_no": (COMPACT, r"[0-9]{10}", "must be 10 digits"),
    "ifsc_code": (COMPACT, r"[A-Z]{4}0[A-Z0-9]{6}", "must be 11 characters: 4 letters, 0, then 6 letters or digits (e.g. SBIN0001234)"),
    "alt_ifsc_code": (COMPACT, r"[A-Z]{4}0[A-Z0-9]{6}", "must be 11 characters: 4 letters, 0, then 6 letters or digits (e.g. SBIN0001234)"),
    "micr_code": (COMPACT, r"[0-9]{9}", "must be 9 digits"),
    "provident_fund_account": (COMPACT, r"(?=.*[0-9])[A-Z0-9/]{5,30}", "may contain only letters, digits and / (5 to 30 characters)"),
    "bank_ac_no": (COMPACT, r"[0-9]{9,18}", "must be 9 to 18 digits"),
    "alt_bank_account_holder": (TRIM, NAME, "may contain only letters, spaces, dot, apostrophe and hyphen"),
    "bank_name": (TRIM, BANK_TEXT, "may contain only letters, digits, spaces and . , & ' ( ) - /"),
    "alt_bank_branch": (TRIM, BANK_TEXT, "may contain only letters, digits, spaces and . , & ' ( ) - /"),
    "iban": (COMPACT, r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", "must be a valid IBAN (country code, 2 check digits, account; e.g. AE070331234567890123456)"),
}


class InvalidBankDetailsError(frappe.ValidationError):
    pass


def normalise(kind, value):
    value = (value or "").strip()
    if kind == TRIM:
        return re.sub(r"\s+", " ", value)
    value = value.upper()
    return re.sub(r"\s+", "", value) if kind == COMPACT else value


def iban_checksum_ok(iban):
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def check_value(fieldname, value):
    """Error text for `value` of `fieldname` (already normalised), or None."""
    _kind, pattern, message = RULES[fieldname]
    if not re.fullmatch(pattern, value):
        return _(message)
    if fieldname == "iban" and not iban_checksum_ok(value):
        return _("has an invalid check digit")
    return None


def validate_bank_details(doc, method=None):
    """Employee.validate: normalise and check the bank / statutory numbers (new or changed only)."""
    meta = frappe.get_meta("Employee")
    errors = []
    for fieldname, (kind, _pattern, _message) in RULES.items():
        if not meta.has_field(fieldname) or not doc.get(fieldname):
            continue
        value = normalise(kind, doc.get(fieldname))
        doc.set(fieldname, value or None)
        if not value or not (doc.is_new() or doc.has_value_changed(fieldname)):
            continue
        error = check_value(fieldname, value)
        if error:
            errors.append(f"<li>{frappe.bold(_(meta.get_label(fieldname)))} {error}</li>")
    if errors:
        frappe.throw(
            _("Please correct these fields:") + f"<ul>{''.join(errors)}</ul>",
            InvalidBankDetailsError,
            title=_("Invalid Bank / Statutory Details"),
        )


@frappe.whitelist()
def check_bank_field(fieldname: str, value: str | None = None) -> dict:
    """Employee form: normalised value and error text of one field, shown as it is entered."""
    if fieldname not in RULES:
        return {"value": value, "error": None}
    value = normalise(RULES[fieldname][0], value)
    error = check_value(fieldname, value) if value else None
    return {"value": value, "error": error}

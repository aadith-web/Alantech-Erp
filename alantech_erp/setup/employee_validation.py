"""Employee validations: one employee per Employee Number (across all companies) and per email."""

import frappe
from frappe import _

def ignore_mandatory_on_create(doc, method=None):
    if doc.is_new():
        doc.flags.ignore_mandatory = True

def validate_unique_employee(doc, method=None):
    """Employee.validate: block a second employee with the same Employee Number, in any company.
    The number cannot be changed once saved (set_only_once, see employee_fields.py)."""
    if not doc.employee_number:
        return
    doc.employee_number = doc.employee_number.strip()

    duplicate = frappe.db.get_value(
        "Employee",
        {
            "employee_number": doc.employee_number,
            "name": ["!=", doc.name or ""],
        },
        ["name", "employee_name"],
        as_dict=True,
    )
    if duplicate:
        frappe.throw(
            _(
                "Employee Number {0} already belongs to {1} ({2}). "
                "To change this employee, use Data Import with Import Type "
                "'Update Existing Records' and ID {2}."
            ).format(
                frappe.bold(doc.employee_number),
                frappe.bold(duplicate.employee_name),
                duplicate.name,
            ),
            frappe.DuplicateEntryError,
            title=_("Duplicate Employee"),
        )


EMAIL_FIELDS = ("company_email", "personal_email")


def validate_unique_email(doc, method=None):
    """Employee.validate: block an email (company or personal) that another employee already has.
    Checked for new employees and changed emails only, so older records that share an email can
    still be saved."""
    for field in EMAIL_FIELDS:
        email = (doc.get(field) or "").strip()
        if not email or not (doc.is_new() or doc.has_value_changed(field)):
            continue
        doc.set(field, email)
        duplicate = None
        for other_field in EMAIL_FIELDS:
            duplicate = frappe.db.get_value(
                "Employee",
                {other_field: email, "name": ["!=", doc.name or ""]},
                ["name", "employee_name"],
                as_dict=True,
            )
            if duplicate:
                break
        if duplicate:
            frappe.throw(
                _("Email {0} already belongs to {1} ({2}).").format(
                    frappe.bold(email), frappe.bold(duplicate.employee_name), duplicate.name
                ),
                frappe.DuplicateEntryError,
                title=_("Duplicate Employee"),
            )


# Employee Numbers run E001, E002, ...; a new employee without one gets the next. The last number
# given is kept in tabSeries, so the number of a deleted employee is never given again.
EMPLOYEE_NUMBER_PREFIX = "E"
EMPLOYEE_NUMBER_DIGITS = 3
EMPLOYEE_NUMBER_SERIES = "alt_employee_number"


def set_employee_number(doc, method=None):
    """Employee.before_insert: fill a blank Employee Number with the next E### number."""
    if (doc.employee_number or "").strip():
        return
    doc.employee_number = next_employee_number()


def next_employee_number():
    """Latest number given + 1: the higher of the stored counter and the highest E<digits> in use
    (an Employee Number typed in by hand may be ahead of the counter). The counter row is locked
    until commit, so two saves at once cannot get the same number."""
    counter = frappe.db.sql(
        "select current from `tabSeries` where name = %s for update", EMPLOYEE_NUMBER_SERIES
    )
    if not counter:
        frappe.db.sql("insert into `tabSeries` (name, current) values (%s, 0)", EMPLOYEE_NUMBER_SERIES)
    in_use = frappe.db.sql(
        """select max(cast(substring(employee_number, %(start)s) as unsigned))
        from `tabEmployee` where employee_number regexp %(pattern)s""",
        {"start": len(EMPLOYEE_NUMBER_PREFIX) + 1, "pattern": f"^{EMPLOYEE_NUMBER_PREFIX}[0-9]+$"},
    )[0][0]
    number = max(counter[0][0] if counter else 0, in_use or 0) + 1
    frappe.db.sql("update `tabSeries` set current = %s where name = %s", (number, EMPLOYEE_NUMBER_SERIES))
    return f"{EMPLOYEE_NUMBER_PREFIX}{number:0{EMPLOYEE_NUMBER_DIGITS}d}"


def seed_employee_number_counter():
    """after_migrate: start the counter at the highest number ever given, deleted employees
    included, so numbers given before the counter existed are not given again."""
    pattern = f"^{EMPLOYEE_NUMBER_PREFIX}[0-9]+$"
    start = len(EMPLOYEE_NUMBER_PREFIX) + 1
    highest = frappe.db.sql(
        """select max(n) from (
            select cast(substring(employee_number, %(start)s) as unsigned) n
            from `tabEmployee` where employee_number regexp %(pattern)s
            union all
            select cast(substring(json_unquote(json_extract(data, '$.employee_number')), %(start)s) as unsigned)
            from `tabDeleted Document` where deleted_doctype = 'Employee'
            and json_unquote(json_extract(data, '$.employee_number')) regexp %(pattern)s
        ) given""",
        {"start": start, "pattern": pattern},
    )[0][0] or 0
    current = frappe.db.get_value("Series", EMPLOYEE_NUMBER_SERIES, "current", order_by=None)
    if current is None:
        frappe.db.sql("insert into `tabSeries` (name, current) values (%s, %s)", (EMPLOYEE_NUMBER_SERIES, highest))
    elif current < highest:
        frappe.db.sql("update `tabSeries` set current = %s where name = %s", (highest, EMPLOYEE_NUMBER_SERIES))
    frappe.db.commit()


def fill_missing_employee_numbers():
    """One-off: numbers for existing employees without one, oldest first."""
    filled = []
    for name in frappe.get_all(
        "Employee", filters={"employee_number": ["is", "not set"]}, pluck="name", order_by="creation asc"
    ):
        number = next_employee_number()
        frappe.db.set_value("Employee", name, "employee_number", number, update_modified=False)
        filled.append(f"{name}: {number}")
    frappe.db.commit()
    return filled



# Mobile is a Phone field (country picker + number, see employee_fields.py), saved as +971-501234567.
MOBILE_TYPES = ("MOBILE", "FIXED_LINE_OR_MOBILE")


def validate_mobile_number(doc, method=None):
    """Employee.validate: Mobile must have a country code and be a mobile number of that country.
    Checked for new employees and changed numbers only (old numbers: patches/v16/employee_mobile_country_code)."""
    if not doc.cell_number or not (doc.is_new() or doc.has_value_changed("cell_number")):
        return
    error = None
    if frappe.flags.in_import:
        doc.cell_number = restore_plus_sign(doc.cell_number)
        error = import_mobile_error(doc.cell_number)
    error = error or check_mobile_number(doc.cell_number)
    if error:
        frappe.throw(error, frappe.InvalidPhoneNumberError, title=_("Invalid Mobile Number"))
    doc.cell_number = format_mobile_number(doc.cell_number)


def restore_plus_sign(mobile):
    """Data Import: spreadsheets (Excel, LibreOffice) read +919876798789 as a formula or a number
    and save 919876798789, without the "+". When the digits are a valid mobile number with the
    "+" (or written 00919876798789), the "+" is put back; anything else is left as it was and
    check_mobile_number reports it. A float cell (919876798789.0) is read as its digits."""
    import re

    value = str(mobile or "").strip()
    if not value or value.startswith("+"):
        return mobile
    value = re.sub(r"\.0+$", "", value)
    digits = re.sub(r"[\s\-().]", "", value)
    if not digits.isdigit():
        return mobile
    if digits.startswith("00"):
        digits = digits[2:]
    candidate = f"+{digits}"
    return candidate if check_mobile_number(candidate) is None else mobile


def import_mobile_error(mobile):
    """Data Import: the error for a number restore_plus_sign could not fix, when its digits start
    with a country code. 97153123567 (UAE, one digit short) gets "+97153123567 is not a valid
    United Arab Emirates mobile number ... Example: +971-501234567" instead of "Select the country
    code", which reads as if the country code were missing. None when there is nothing to add."""
    import re

    import phonenumbers

    value = re.sub(r"\.0+$", "", str(mobile or "").strip())
    digits = re.sub(r"[\s\-().]", "", value)
    if not digits.isdigit() or value.startswith("+"):
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    try:
        number = phonenumbers.parse(f"+{digits}")
    except phonenumbers.NumberParseException:
        return None
    region = phonenumbers.region_code_for_country_code(number.country_code)
    if not region or region == phonenumbers.UNKNOWN_REGION:
        return None
    error = check_mobile_number(f"+{digits}")
    if not error:
        return None
    return error + " " + _("If {0} has no country code, add + and the country code before the number.").format(
        frappe.bold(mobile)
    )


@frappe.whitelist()
def check_mobile_number(mobile):
    """The reason the mobile number is not valid for its country code, or None if it is."""
    import phonenumbers

    mobile = (mobile or "").strip()
    if not mobile:
        return None
    if not mobile.startswith("+"):
        return _("Select the country code for Mobile {0}.").format(frappe.bold(mobile))
    try:
        number = phonenumbers.parse(mobile)
    except phonenumbers.NumberParseException:
        return _("Mobile {0} has no valid country code.").format(frappe.bold(mobile))

    region = phonenumbers.region_code_for_number(number) or phonenumbers.region_code_for_country_code(number.country_code)
    number_type = phonenumbers.PhoneNumberType.to_string(phonenumbers.number_type(number))
    if phonenumbers.is_valid_number(number) and number_type in MOBILE_TYPES:
        return None

    country = frappe.db.get_value("Country", {"code": (region or "").lower()}, "name") or region
    example = phonenumbers.example_number_for_type(region, phonenumbers.PhoneNumberType.MOBILE)
    return _("{0} is not a valid {1} mobile number (+{2}).{3}").format(
        frappe.bold(mobile),
        country or _("country code"),
        number.country_code,
        " " + _("Example: {0}").format(frappe.bold(format_mobile_number(example))) if example else "",
    )


def format_mobile_number(number, region=None):
    """+971-501234567, the way the Phone field shows the country code and number.
    `number` is a phonenumbers.PhoneNumber or a string (with + or a country code in `region`)."""
    import phonenumbers

    if isinstance(number, str):
        number = phonenumbers.parse(number, region)
    return f"+{number.country_code}-{phonenumbers.national_significant_number(number)}"


# Employees are at least MINIMUM_AGE years old on their Date of Joining (today when it is blank).
MINIMUM_AGE = 18


class UnderageEmployeeError(frappe.ValidationError):
    pass


def age_on(date_of_birth, on_date):
    """Completed years between the two dates."""
    from dateutil.relativedelta import relativedelta
    from frappe.utils import getdate

    return relativedelta(getdate(on_date), getdate(date_of_birth)).years


def validate_minimum_age(doc, method=None):
    """Employee.validate: 18 or older on the Date of Joining. New employees and changed Date of
    Birth / Date of Joining only, so system saves of older records are not blocked."""
    from frappe.utils import formatdate, today

    if not doc.date_of_birth:
        return
    if not (doc.is_new() or doc.has_value_changed("date_of_birth") or doc.has_value_changed("date_of_joining")):
        return
    on_date = doc.date_of_joining or today()
    age = age_on(doc.date_of_birth, on_date)
    if age >= MINIMUM_AGE:
        return
    frappe.throw(
        _(
            "The employee must be at least {0} years old on the Date of Joining ({1}). "
            "With Date of Birth {2} they are {3}."
        ).format(
            MINIMUM_AGE,
            formatdate(on_date),
            frappe.bold(formatdate(doc.date_of_birth)),
            max(age, 0),
        ),
        UnderageEmployeeError,
        title=_("Invalid Date of Birth"),
    )


# Needed to create an employee (form and Data Import). New employees only, so existing records
# that miss one can still be saved. Department and Reports To may come from the designation
# (org_structure.apply_designation_defaults, which runs before this). Same list in employee.js.
REQUIRED_ON_CREATE = (
    "first_name", "gender", "date_of_birth", "date_of_joining", "company", "status",
    "department", "designation", "branch", "employment_type", "cell_number",
    "default_shift", "grade",
)


# still required on first creation; the rest of REQUIRED_ON_CREATE is not (see validate_required_on_create)
ALWAYS_ON_CREATE = ("first_name", "gender")


def missing_required_fields(doc):
    """Fieldnames of REQUIRED_ON_CREATE that are blank, plus EMAIL_FIELDS (the tuple) when both
    emails are blank. Reports To is not needed for the top designation."""
    from alantech_erp.org_structure import TOP_DESIGNATION

    missing = [
        field
        for field in REQUIRED_ON_CREATE
        if not doc.get(field) and not (field == "reports_to" and doc.designation == TOP_DESIGNATION)
    ]
    if not any((doc.get(field) or "").strip() for field in EMAIL_FIELDS):
        missing.append(EMAIL_FIELDS)
    return missing


def validate_required_on_create(doc, method=None):
    """Employee.validate: refuse a new employee without the fields in REQUIRED_ON_CREATE and an email."""
    # tests create bare employees; a test of this rule sets the flag
    if frappe.flags.in_test and not frappe.flags.alt_check_employee_required:
        return
    meta = frappe.get_meta("Employee")
    missing = [
        _(meta.get_label(field)) if field != EMAIL_FIELDS else _("Company Email or Personal Email")
        for field in missing_required_fields(doc) if not doc.is_new() or field in ALWAYS_ON_CREATE
    ]
    if missing:
        frappe.throw(
            _("Enter these to save the employee: {0}").format(", ".join(frappe.bold(m) for m in missing)),
            frappe.MandatoryError,
            title=_("Missing Fields"),
        )

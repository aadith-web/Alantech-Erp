"""Employee validations: one employee per Employee Number (across all companies) and per email."""

import frappe
from frappe import _


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
    error = check_mobile_number(doc.cell_number)
    if error:
        frappe.throw(error, frappe.InvalidPhoneNumberError, title=_("Invalid Mobile Number"))
    doc.cell_number = format_mobile_number(doc.cell_number)


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


# Needed to create an employee (form and Data Import). New employees only, so existing records
# that miss one can still be saved. Department and Reports To may come from the designation
# (org_structure.apply_designation_defaults, which runs before this). Same list in employee.js.
REQUIRED_ON_CREATE = (
    "first_name", "gender", "date_of_birth", "date_of_joining", "company", "status",
    "department", "designation", "branch", "reports_to", "employment_type", "cell_number",
    "default_shift",
)


def validate_required_on_create(doc, method=None):
    """Employee.validate: refuse a new employee without the fields in REQUIRED_ON_CREATE and an email."""
    if not doc.is_new():
        return
    # tests create bare employees; a test of this rule sets the flag
    if frappe.flags.in_test and not frappe.flags.alt_check_employee_required:
        return
    from alantech_erp.org_structure import TOP_DESIGNATION

    meta = frappe.get_meta("Employee")
    missing = [
        _(meta.get_label(field))
        for field in REQUIRED_ON_CREATE
        if not doc.get(field) and not (field == "reports_to" and doc.designation == TOP_DESIGNATION)
    ]
    if not any((doc.get(field) or "").strip() for field in EMAIL_FIELDS):
        missing.append(_("Company Email or Personal Email"))
    if missing:
        frappe.throw(
            _("Enter these to create the employee: {0}").format(", ".join(frappe.bold(m) for m in missing)),
            frappe.MandatoryError,
            title=_("Missing Fields"),
        )

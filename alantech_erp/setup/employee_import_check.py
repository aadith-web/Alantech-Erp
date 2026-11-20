"""Employee import: every error of the whole file in one list, before anything is imported.

ClickUp: https://app.clickup.com/t/14yr2e587b3 (Show All Errors Together in Employee Excel Import)

Without this, the first failing check of a row stopped that row (frappe.throw), so the user fixed
one error, re-uploaded and only then saw the next one. Now, when the file is uploaded (and again
when Start Import is clicked), every row is checked the way a save would check it, and each
problem is listed in the import preview as "Row <n> - <Field>: <message>":

- fields needed to create an employee (employee_validation.REQUIRED_ON_CREATE, one entry per
  missing field) and the DocType's own mandatory fields;
- email addresses (Company / Personal / Preferred Email);
- every Employee validate hook in hooks.py (mobile number, Reports To, unique Employee Number and
  email, minimum age, Nationality, Aadhaar / PAN, ...), each run on its own so one error does not
  hide the next;
- the HRMS / ERPNext Employee checks (dates, status, Reports To, preferred email);
- the same Employee Number or email used on two rows of the file.

Frappe's own column checks (unknown Link / Select values, dates in the wrong format) are listed in
the same preview as before. Any error blocks the import until it is fixed in the file or the row
is skipped (Skip Row), so nothing is half imported.

The check runs inside a savepoint that is rolled back, with frappe.flags.in_import set as during
the import (employee_validation.restore_plus_sign). Hooked as data_import_providers["Employee"];
import_row keeps Frappe's normal insert / update.
"""

import frappe
from frappe import _
from frappe.core.doctype.data_import.import_provider import ImportProvider
from frappe.core.doctype.data_import.importer import INSERT, UPDATE, df_as_json, get_id_field
from frappe.utils import cstr, strip_html

from alantech_erp.setup.employee_validation import EMAIL_FIELDS, missing_required_fields

DOCTYPE = "Employee"
SAVEPOINT = "alt_employee_import_check"
NEW_NAME = "new-employee-import-check"
REPORTS_TO = "reports_to"

# The validate hooks that report missing fields themselves are replaced by the per-field list
SKIPPED_HOOKS = (
    "alantech_erp.setup.employee_validation.validate_required_on_create",
    "alantech_erp.setup.employee_nationality.validate_nationality",
)

# Field shown with the error of each check. Several fields: the one whose value is in the message.
HOOK_FIELDS = {
    "alantech_erp.setup.reports_to.validate_reports_to": ("reports_to",),
    "alantech_erp.setup.employee_validation.validate_unique_employee": ("employee_number",),
    "alantech_erp.setup.employee_validation.validate_unique_email": EMAIL_FIELDS,
    "alantech_erp.setup.employee_validation.validate_mobile_number": ("cell_number",),
    "alantech_erp.setup.employee_validation.validate_minimum_age": ("date_of_birth", "date_of_joining"),
    "alantech_erp.setup.employee_nationality.validate_indian_ids": ("alt_aadhaar_number", "pan_number"),
}

# HRMS / ERPNext Employee controller checks, in the order Employee.validate runs them
CONTROLLER_CHECKS = (
    ("validate_date", ("date_of_birth", "date_of_joining", "relieving_date", "final_confirmation_date")),
    ("validate_email", ("company_email", "personal_email", "prefered_email")),
    ("validate_status", ("status",)),
    ("validate_reports_to", ("reports_to",)),
    ("validate_preferred_email", ("prefered_contact_email", "prefered_email")),
)

# Not filled in the file but set on save: naming series (Employee.autoname), name (validate)
MANDATORY_SET_ON_SAVE = ("naming_series", "employee_name")

# Must be unique across employees: also checked between the rows of the file
UNIQUE_IN_FILE = (("employee_number",), EMAIL_FIELDS)


class EmployeeImportProvider(ImportProvider):
    def validate(self, import_file):
        return check_import_file(import_file)

    def import_row(self, importer, doc):
        """Frappe's own insert / update (Importer.process_doc without a provider)."""
        if importer.import_type == INSERT:
            return importer.insert_record(doc), None
        if importer.import_type == UPDATE:
            return importer.update_record(doc), None
        return importer.upsert_record(doc)


def check_import_file(import_file):
    """Warnings {"row", "col", "field", "message"} for every problem in every row of the file."""
    if not getattr(import_file, "data", None):
        return []
    columns = {col.df.fieldname: col for col in import_file.columns if col.df and col.df.parent == DOCTYPE}
    payloads = parse_rows(import_file)
    resolve_reports_to, in_file = reports_to_resolver(import_file, payloads)

    warnings = []
    failed = []  # logged after the rollback, which would undo the Error Log
    in_import = frappe.flags.in_import
    messages = list(frappe.local.message_log)
    frappe.db.savepoint(SAVEPOINT)
    try:
        frappe.flags.in_import = True
        for payload in payloads:
            row = payload.rows[0].row_number
            values = frappe._dict(payload.doc)
            reports_to = cstr(values.get(REPORTS_TO)).strip()
            values[REPORTS_TO] = resolve_reports_to.get(reports_to, values.get(REPORTS_TO))
            try:
                errors = check_employee(values, import_file.import_type)
                if reports_to and reports_to in in_file:
                    # an employee of this file: not created yet, so not checked as a manager
                    errors = [e for e in errors if e[0] != REPORTS_TO]
            except Exception:
                # an unexpected failure must not break the preview; the import reports the row
                failed.append((row, frappe.get_traceback()))
                continue
            warnings += [as_warning(row, fieldname, message, columns) for fieldname, message in errors]
        warnings += duplicates_in_file(payloads, columns)
    finally:
        frappe.db.rollback(save_point=SAVEPOINT)
        frappe.flags.in_import = in_import
        frappe.local.message_log = messages
    for row, traceback in failed:
        frappe.log_error(title=f"Employee import check failed for row {row}", message=traceback)
    return sorted(warnings, key=lambda w: w["row"])


def reports_to_resolver(import_file, payloads):
    """Reports To in the file may be the manager's name (Employee Name, the tree alias) instead of
    the ID; the import swaps it for the ID when it saves the row (Importer._resolve_tree_parent_link).
    Returns ({file value: employee ID} for employees in the database, {values naming a row of
    this file})."""
    from frappe.core.doctype.data_import.importer import _build_db_tree_parent_name_map

    values = {cstr(p.doc.get(REPORTS_TO)).strip() for p in payloads} - {""}
    header = import_file.header
    file_refs = (getattr(header, "import_ids", None) or set()) | (getattr(header, "import_aliases", None) or set())
    # the import also knows a saved row by its Employee Name (First + Middle + Last Name)
    file_refs |= {
        " ".join(cstr(p.doc.get(f)).strip() for f in ("first_name", "middle_name", "last_name") if cstr(p.doc.get(f)).strip())
        for p in payloads
    }
    in_file = values & file_refs
    alias_field = getattr(header, "tree_alias_field", None)
    to_fetch = values - in_file
    resolved = _build_db_tree_parent_name_map(DOCTYPE, to_fetch, alias_field) if to_fetch and alias_field else {}
    return resolved, in_file


def parse_rows(import_file):
    """The file's records, without leaving the parse warnings on the rows a second time (Frappe
    collects them itself when it parses the file for the import)."""
    saved = [list(row.warnings) for row in import_file.data]
    try:
        return import_file.get_payloads_for_import()
    finally:
        for row, warnings in zip(import_file.data, saved, strict=True):
            row.warnings = warnings


def check_employee(values, import_type):
    """[(fieldname or None, message)] for one record, every check run on its own."""
    doc = build_employee(values, import_type)
    errors = []

    def run(check, fields=()):
        try:
            check()
        # frappe.throw errors; DuplicateEntryError (unique number / email / Aadhaar) is a NameError
        except (frappe.ValidationError, frappe.NameError) as e:
            message = error_message(e)
            if message:
                errors.append((pick_field(doc, fields, message), message))

    for method, fields in CONTROLLER_CHECKS:
        if method == "validate_preferred_email" and hasattr(doc, "set_preferred_email"):
            run(doc.set_preferred_email)
        if hasattr(doc, method):
            run(getattr(doc, method), fields)
    if hasattr(doc, "set_employee_name"):
        doc.set_employee_name()

    for path in validate_hooks():
        if path in SKIPPED_HOOKS:
            continue
        run(lambda path=path: frappe.get_attr(path)(doc, "validate"), HOOK_FIELDS.get(path, ()))

    errors += email_errors(doc)
    if doc.is_new():
        errors += missing_field_errors(doc)

    unique = []
    for error in errors:  # a check of HRMS and one of ours may report the same thing
        if error not in unique:
            unique.append(error)
    return unique


def build_employee(values, import_type):
    """The Employee the import would save: a new one, or the existing one with the file's values."""
    id_field = get_id_field(DOCTYPE).fieldname
    if import_type != INSERT and values.get(id_field) and frappe.db.exists(DOCTYPE, values.get(id_field)):
        doc = frappe.get_doc(DOCTYPE, values.get(id_field))
        doc.update(values)
        return doc
    doc = frappe.new_doc(DOCTYPE)
    doc.update(values)
    # a save names the employee before validate; HRMS's validate_reports_to compares with it
    doc.set("name", NEW_NAME)
    return doc


def validate_hooks():
    """Employee validate doc_events of all apps ("*" first), in the order a save runs them."""
    doc_events = frappe.get_hooks("doc_events") or {}
    paths = []
    for key in ("*", DOCTYPE):
        hooks = (doc_events.get(key) or {}).get("validate") or []
        paths += [hooks] if isinstance(hooks, str) else list(hooks)
    return paths


def email_errors(doc):
    """Email fields of the DocType (options Email) that are not valid addresses."""
    from frappe.utils import split_emails, validate_email_address

    errors = []
    for df in doc.meta.get_data_fields():
        value = doc.get(df.fieldname)
        if df.options != "Email" or not value:
            continue
        for email in split_emails(value):
            if not validate_email_address(email):
                errors.append((df.fieldname, _("{0} is not a valid Email Address").format(frappe.bold(email))))
    return errors


def missing_field_errors(doc):
    """One error per missing field: the DocType's mandatory fields and REQUIRED_ON_CREATE."""
    errors = []
    for fieldname, _message in doc._get_missing_mandatory_fields():
        if fieldname not in MANDATORY_SET_ON_SAVE:
            errors.append((fieldname, _("Value missing")))
    # as in validate_required_on_create / validate_nationality: tests create bare employees
    if frappe.flags.in_test and not frappe.flags.alt_check_employee_required:
        return errors
    for field in missing_required_fields(doc):
        if field == EMAIL_FIELDS:
            errors.append((None, _("Enter Company Email or Personal Email.")))
        else:
            errors.append((field, _("Value missing")))
    if not (doc.get("alt_nationality") or "").strip() and doc.meta.has_field("alt_nationality"):
        errors.append(("alt_nationality", _("Citizen is required. Please select Nationality.")))
    return errors


def duplicates_in_file(payloads, columns):
    """The same Employee Number / email on two rows: reported on the later row."""
    warnings = []
    for fields in UNIQUE_IN_FILE:
        first_row = {}
        for payload in payloads:
            row = payload.rows[0].row_number
            for fieldname in fields:
                value = cstr(payload.doc.get(fieldname)).strip().lower()
                if not value:
                    continue
                if value in first_row and first_row[value] != row:
                    message = _("{0} is also in row {1} of this file.").format(
                        frappe.bold(payload.doc.get(fieldname)), first_row[value]
                    )
                    warnings.append(as_warning(row, fieldname, message, columns))
                else:
                    first_row.setdefault(value, row)
    return warnings


def error_message(exception):
    """The text of a frappe.throw, without HTML tags other than <b>."""
    message = cstr(exception.args[0] if exception.args else exception)
    return strip_html(message.replace("<b>", "[[b]]").replace("</b>", "[[/b]]")).replace(
        "[[b]]", "<b>"
    ).replace("[[/b]]", "</b>").strip()


def pick_field(doc, fields, message):
    """Of the check's fields, the one whose value is in the message, else the first."""
    plain = strip_html(message)
    for fieldname in fields:
        value = cstr(doc.get(fieldname)).strip()
        if value and value in plain:
            return fieldname
    return fields[0] if fields else None


def as_warning(row, fieldname, message, columns):
    """A Data Import warning: shown as "Row <row>" with "<Field label>: <message>"."""
    warning = {"row": row, "message": message}
    if fieldname:
        col = columns.get(fieldname)
        df = col.df if col else frappe.get_meta(DOCTYPE).get_field(fieldname)
        if df:
            warning["field"] = df_as_json(df)
        if col:
            warning["col"] = col.column_number
    return warning

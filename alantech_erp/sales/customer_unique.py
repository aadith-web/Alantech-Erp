"""One customer per mobile number, email and GSTIN (CRM-F04 Customer Creation Management).

Customer (doc_events)
  before_validate  Mobile No / Email ID taken from the Primary Contact when the form has none
                   (converted Lead, saved customer), and their cleaned-up keys set:
                   alt_mobile_key  +919847012345  (spaces, dashes, leading 0 / 00 removed, country code)
                   alt_email_key   lower case, trimmed
  validate         Mobile No and Email ID mandatory, valid email and a mobile number with its country
                   code; then the "already exists" check for a new customer and for changed values:
                   Mobile No, Email ID  another customer, or a contact of another customer
                   GSTIN                another customer
                   Customer Name        Company / Partnership: same name blocked; similar names
                                        ("ABC Pvt Ltd" / "ABC Private Limited") and Individuals with
                                        the same name only warned
                   Disabled customers count: the message asks to enable the existing one instead.
                   Runs for the form, quick entry, Lead -> Customer and Data Import alike.
Contact (doc_events)  a contact of a customer cannot take another customer's mobile / email; the
                   Primary Contact's mobile and email are copied to its customers.

alt_mobile_key / alt_email_key get a unique index (setup/sales_flow.py) once the existing customers
have no duplicates, so two saves at the same moment cannot both get through.
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr, get_link_to_form, validate_email_address

from alantech_erp.sales import EMAIL_KEY_FIELD, INDIVIDUAL, MOBILE_KEY_FIELD

# Legal-form words ignored when comparing company names
_NAME_NOISE = {
	"the",
	"and",
	"pvt",
	"private",
	"ltd",
	"limited",
	"llc",
	"llp",
	"inc",
	"incorporated",
	"co",
	"company",
	"corp",
	"corporation",
	"plc",
	"fze",
	"fzc",
	"fzco",
	"fzllc",
	"est",
	"establishment",
}


# --------------------------------------------------------------------------- keys
def default_region():
	"""Phone region (IN, AE...) for numbers saved without a country code: System Settings country."""
	country = frappe.db.get_single_value("System Settings", "country")
	code = frappe.get_cached_value("Country", country, "code") if country else None
	return (code or "in").upper()


def mobile_key(mobile, region=None):
	"""+919847012345 for "+91-98470 12345", "0091 9847012345" or (region IN) "09847012345"."""
	raw = cstr(mobile).strip()
	if not raw:
		return None
	if raw.startswith("00"):
		raw = "+" + raw[2:]
	try:
		import phonenumbers

		number = phonenumbers.parse(raw, None if raw.startswith("+") else (region or default_region()))
		return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
	except Exception:
		digits = re.sub(r"\D", "", raw).lstrip("0")
		return f"+{digits}" if digits else None


def email_key(email):
	return cstr(email).strip().lower() or None


def name_key(name):
	"""Company name without case, punctuation and legal-form words: "abc water" for "ABC Water Pvt. Ltd."."""
	text = cstr(name).lower().replace("&", " and ").replace(".", "")  # L.L.C. -> llc
	words = re.sub(r"[^a-z0-9]+", " ", text).split()
	return " ".join(w for w in words if w not in _NAME_NOISE)


# --------------------------------------------------------------------------- Customer
def _skip():
	flags = frappe.flags
	return bool(flags.in_migrate or flags.in_install or flags.in_patch or flags.in_fixtures)


def _has_keys():
	meta = frappe.get_meta("Customer")
	return meta.has_field(MOBILE_KEY_FIELD) and meta.has_field(EMAIL_KEY_FIELD)


def before_validate(doc, method=None):
	contact = doc.get("customer_primary_contact")
	if contact and not (doc.get("mobile_no") and doc.get("email_id")):
		values = frappe.db.get_value("Contact", contact, ["mobile_no", "email_id"], as_dict=True) or {}
		for field in ("mobile_no", "email_id"):
			if not doc.get(field) and values.get(field):
				doc.set(field, values.get(field))
	if doc.get("email_id"):
		doc.email_id = doc.email_id.strip()
	if doc.get("customer_name"):
		doc.customer_name = re.sub(r"\s+", " ", doc.customer_name).strip()
	if _has_keys():
		doc.set(MOBILE_KEY_FIELD, mobile_key(doc.get("mobile_no")))
		doc.set(EMAIL_KEY_FIELD, email_key(doc.get("email_id")))


def validate(doc, method=None):
	if _skip():
		return
	check_contact_details(doc)
	check_duplicates(doc)


def _changed(doc, field):
	if doc.is_new():
		return True
	before = doc.get_doc_before_save()
	return not before or cstr(before.get(field)).strip() != cstr(doc.get(field)).strip()


def check_contact_details(doc):
	"""Mobile No and Email ID are mandatory, the email valid and the mobile with its country code."""
	from alantech_erp.setup.employee_validation import check_mobile_number, format_mobile_number

	missing = [_(doc.meta.get_label(f)) for f in ("mobile_no", "email_id") if not doc.get(f)]
	if missing:
		names = (" " + _("and") + " ").join(frappe.bold(m) for m in missing)
		if doc.is_new() or not doc.get("customer_primary_contact"):
			message = _("Enter the {0} of the customer (mandatory).").format(names)
			if not doc.is_new():
				message += " " + _("Add a Primary Contact with the mobile number and email.")
		else:
			message = _("{0} mandatory: add it to the Primary Contact {1}.").format(
				names, get_link_to_form("Contact", doc.customer_primary_contact)
			)
		frappe.throw(message, title=_("Mobile No and Email ID Required"))

	if _changed(doc, "email_id") and not validate_email_address(doc.email_id):
		frappe.throw(
			_("{0} is not a valid Email ID.").format(frappe.bold(doc.email_id)), title=_("Invalid Email ID")
		)
	if _changed(doc, "mobile_no"):
		if doc.is_new() and doc.mobile_no.strip().startswith("00"):
			doc.mobile_no = "+" + doc.mobile_no.strip()[2:]  # 0091... -> +91...
		error = check_mobile_number(doc.mobile_no)
		if error:
			where = ""
			if not doc.is_new() and doc.get("customer_primary_contact"):
				where = " " + _("(Primary Contact {0})").format(
					get_link_to_form("Contact", doc.customer_primary_contact)
				)
			frappe.throw(error + where, title=_("Invalid Mobile No"))
		if doc.is_new():
			# the quick entry / form makes the Primary Contact from this value
			doc.mobile_no = format_mobile_number(doc.mobile_no)
			if _has_keys():
				doc.set(MOBILE_KEY_FIELD, mobile_key(doc.mobile_no))


def check_duplicates(doc):
	"""Block a customer whose mobile, email, GSTIN or (company) name another customer already has."""
	found = []  # (label, value, customer name, customer customer_name, disabled)
	keys = _has_keys()

	if keys and doc.get(MOBILE_KEY_FIELD) and _changed(doc, MOBILE_KEY_FIELD):
		found += [
			(_("Mobile No"), doc.mobile_no, *c)
			for c in customers_with_mobile(doc.get(MOBILE_KEY_FIELD), doc.name)
		]
	if keys and doc.get(EMAIL_KEY_FIELD) and _changed(doc, EMAIL_KEY_FIELD):
		found += [
			(_("Email ID"), doc.email_id, *c)
			for c in customers_with_email(doc.get(EMAIL_KEY_FIELD), doc.name)
		]
	gstin = cstr(doc.get("gstin")).strip().upper()
	if gstin and doc.meta.has_field("gstin") and _changed(doc, "gstin"):
		found += [(_("GSTIN"), gstin, *c) for c in _customers({"gstin": gstin}, doc.name)]
	is_company = doc.get("customer_type") != INDIVIDUAL
	if doc.customer_name and is_company and _changed(doc, "customer_name"):
		found += [
			(_("Customer Name"), doc.customer_name, *c)
			for c in _customers({"customer_name": doc.customer_name}, doc.name)
		]

	if found:
		frappe.throw(
			_duplicate_message(found), frappe.DuplicateEntryError, title=_("Customer Already Exists")
		)

	if doc.customer_name and _changed(doc, "customer_name"):
		_warn_similar_names(doc, exact=not is_company)


def _customers(filters, exclude):
	rows = frappe.get_all(
		"Customer",
		filters={**filters, "name": ["!=", exclude or ""]},
		fields=["name", "customer_name", "disabled"],
		limit=5,
	)
	return [(r.name, r.customer_name, r.disabled) for r in rows]


def _contact_customers(child, value_field, value, exclude):
	"""Customers (other than `exclude`) with a contact that has `value` in its phone / email rows."""
	return frappe.db.sql(
		f"""
		select distinct c.name, c.customer_name, c.disabled, v.{value_field}
		from `tab{child}` v
		join `tabDynamic Link` dl on dl.parent = v.parent and dl.parenttype = 'Contact'
			and dl.link_doctype = 'Customer'
		join `tabCustomer` c on c.name = dl.link_name
		where v.parenttype = 'Contact' and c.name != %(exclude)s and {value}
		limit 50
		""",
		{"exclude": exclude or ""},
		as_dict=True,
	)


def customers_with_mobile(key, exclude=None):
	result = {c[0]: c for c in _customers({MOBILE_KEY_FIELD: key}, exclude)}
	tail = re.sub(r"\D", "", key)[-8:]
	cleaned = (
		"replace(replace(replace(replace(replace(v.phone, ' ', ''), '-', ''), '(', ''), ')', ''), '.', '')"
	)
	condition = f"{cleaned} like {frappe.db.escape('%' + tail)}"
	for row in _contact_customers("Contact Phone", "phone", condition, exclude):
		if row.name not in result and mobile_key(row.phone) == key:
			result[row.name] = (row.name, row.customer_name, row.disabled)
	return list(result.values())


def customers_with_email(key, exclude=None):
	result = {c[0]: c for c in _customers({EMAIL_KEY_FIELD: key}, exclude)}
	condition = f"lower(trim(v.email_id)) = {frappe.db.escape(key)}"
	for row in _contact_customers("Contact Email", "email_id", condition, exclude):
		if row.name not in result:
			result[row.name] = (row.name, row.customer_name, row.disabled)
	return list(result.values())


def _duplicate_message(found):
	lines = []
	for label, value, name, customer_name, disabled in found:
		line = _("Customer already exists with this {0} {1}: {2}").format(
			label,
			frappe.bold(value),
			get_link_to_form(
				"Customer", name, f"{name} - {customer_name}" if customer_name != name else name
			),
		)
		if disabled:
			line += " " + _("(disabled: enable that customer instead of creating a new one)")
		lines.append(f"<li>{line}</li>")
	return f"<ul>{''.join(lines)}</ul>" + _("Open the existing customer instead of creating a new one.")


def _warn_similar_names(doc, exact=False):
	"""Warn (do not block) about customers with a similar name."""
	key = name_key(doc.customer_name)
	if not key:
		return
	first_word = key.split()[0]
	candidates = frappe.get_all(
		"Customer",
		filters={"customer_name": ["like", f"%{first_word}%"], "name": ["!=", doc.name or ""]},
		fields=["name", "customer_name"],
		limit=200,
	)
	similar = [
		c
		for c in candidates
		if name_key(c.customer_name) == key
		and (exact or c.customer_name.casefold() != doc.customer_name.casefold())
	][:5]
	if similar:
		links = ", ".join(get_link_to_form("Customer", c.name, c.customer_name) for c in similar)
		frappe.msgprint(
			_(
				"A customer with a similar name already exists: {0}. Check it is not the same customer."
			).format(links),
			title=_("Similar Customer"),
			indicator="orange",
			alert=bool(frappe.flags.in_import),
		)


# --------------------------------------------------------------------------- Contact
def _linked_customers(contact):
	return [
		link.link_name
		for link in contact.get("links") or []
		if link.link_doctype == "Customer" and link.link_name
	]


def contact_validate(doc, method=None):
	"""A customer's contact cannot take a mobile number / email another customer already has."""
	if _skip() or not _has_keys():
		return
	customers = _linked_customers(doc)
	if not customers:
		return
	before = doc.get_doc_before_save()
	old_phones = {mobile_key(p.phone) for p in (before.get("phone_nos") if before else [])}
	old_emails = {email_key(e.email_id) for e in (before.get("email_ids") if before else [])}

	found = []
	for row in doc.get("phone_nos") or []:
		key = mobile_key(row.phone)
		if key and key not in old_phones:
			found += [
				(_("Mobile No"), row.phone, *c) for c in customers_with_mobile(key) if c[0] not in customers
			]
	for row in doc.get("email_ids") or []:
		key = email_key(row.email_id)
		if key and key not in old_emails:
			found += [
				(_("Email ID"), row.email_id, *c) for c in customers_with_email(key) if c[0] not in customers
			]
	if found:
		frappe.throw(
			_duplicate_message(found), frappe.DuplicateEntryError, title=_("Customer Already Exists")
		)


def contact_on_update(doc, method=None):
	"""Copy the Primary Contact's mobile / email (and their keys) to its customers."""
	if not _has_keys():
		return
	for customer in frappe.get_all("Customer", filters={"customer_primary_contact": doc.name}, pluck="name"):
		values = {
			"mobile_no": doc.mobile_no,
			"email_id": doc.email_id,
			MOBILE_KEY_FIELD: mobile_key(doc.mobile_no),
			EMAIL_KEY_FIELD: email_key(doc.email_id),
		}
		current = frappe.db.get_value("Customer", customer, list(values), as_dict=True)
		if any(cstr(current.get(k)) != cstr(v) for k, v in values.items()):
			frappe.db.set_value("Customer", customer, values, update_modified=False)


# --------------------------------------------------------------------------- setup (after_migrate)
KEY_FIELDS = [
	{
		"fieldname": MOBILE_KEY_FIELD,
		"label": "Mobile No (duplicate check)",
		"fieldtype": "Data",
		"insert_after": "email_id",
		"hidden": 1,
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
		"report_hide": 1,
	},
	{
		"fieldname": EMAIL_KEY_FIELD,
		"label": "Email ID (duplicate check)",
		"fieldtype": "Data",
		"insert_after": MOBILE_KEY_FIELD,
		"hidden": 1,
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
		"report_hide": 1,
	},
]


def setup_keys():
	"""Create the key fields, fill them for existing customers, then make them unique in the database
	(left as a plain index, with a message, while existing customers still share a value)."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	for df in KEY_FIELDS:
		if not frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": df["fieldname"]}):
			create_custom_field("Customer", {**df, "search_index": 1})
	frappe.clear_cache(doctype="Customer")

	region = default_region()
	for row in frappe.get_all(
		"Customer", fields=["name", "mobile_no", "email_id", MOBILE_KEY_FIELD, EMAIL_KEY_FIELD]
	):
		values = {
			MOBILE_KEY_FIELD: mobile_key(row.mobile_no, region),
			EMAIL_KEY_FIELD: email_key(row.email_id),
		}
		if any(cstr(row.get(k)) != cstr(v) for k, v in values.items()):
			frappe.db.set_value("Customer", row.name, values, update_modified=False)

	for fieldname in (MOBILE_KEY_FIELD, EMAIL_KEY_FIELD):
		name = frappe.db.get_value("Custom Field", {"dt": "Customer", "fieldname": fieldname})
		field = frappe.get_doc("Custom Field", name)
		if field.unique:
			continue
		duplicates = frappe.db.sql(
			f"""select `{fieldname}`, count(*) from `tabCustomer` where ifnull(`{fieldname}`, '') != ''
			group by `{fieldname}` having count(*) > 1 limit 20"""
		)
		if duplicates:
			print(
				f"alantech_erp: Customer {fieldname} not made unique yet, customers share: "
				+ ", ".join(d[0] for d in duplicates)
				+ " (merge or correct them, then run bench migrate again)"
			)
			continue
		field.unique = 1
		field.search_index = 0
		field.save(ignore_permissions=True)

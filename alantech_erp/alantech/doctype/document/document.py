import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_fullname, get_link_to_form, getdate, now_datetime, today

from alantech_erp.alantech.doctype.document.document_files import file_restrictions, validate_attachments
from alantech_erp.alantech.doctype.document.document_number import validate_document_number
from alantech_erp.alantech.doctype.document.employee_numbers import fill_from_employee, update_employee

DOCTYPE = "Document"
APPROVER_ROLE = "HR Manager"
UNRESTRICTED_ROLES = {"System Manager", "HR Manager", "HR User"}
INACTIVE_EMPLOYEE_STATUSES = ("Inactive", "Left")
PENDING, APPROVED, REJECTED = "Pending Approval", "Approved", "Rejected"

# Set only by the server, never accepted from the browser
APPROVAL_FIELDS = ("approval_status", "submitted_by", "reviewed_by", "reviewed_on", "rejection_reason")
# A change to any of these counts as an edit
CONTENT_FIELDS = ("reference_doctype", "reference_name", "document_type", "card_number", "issue_date",
                  "place_of_issue", "expiry_date", "issuing_country", "remarks")


class Document(Document):
	def onload(self):
		self.set_onload("file_restrictions", file_restrictions())  # upload dialog (document.js)

	def validate(self):
		self.set_reference_details()
		self.validate_reference_access()
		self.validate_dates()
		validate_attachments(self)  # PDF / JPG / PNG, at most 5 MB
		fill_from_employee(self)  # new Aadhaar / PAN document: the Employee's number (employee_numbers.py)
		validate_document_number(self)  # also blocks approving a wrong number until it is fixed
		if self.flags.approval_action:      # approve()/reject() set the fields themselves
			return
		review = self.get_review_request()  # HR Manager chose Approved / Rejected in the form
		self.restore_approval_fields()
		if review:
			self.apply_review(*review)
			return
		self.set_approval_status()

	def on_update(self):
		update_employee(self)  # approved Aadhaar / PAN number -> Employee (employee_numbers.py)
		if self.flags.timeline_note:
			self.add_comment("Info", self.flags.timeline_note)   # shows in Activity Log
		if self.flags.notify_hr:
			self.flags.notify_hr = False  # once per change, even if this object is saved again
			notify_hr_managers(self)
		if self.flags.review_outcome:
			outcome, self.flags.review_outcome = self.flags.review_outcome, None
			reviewer = get_fullname(frappe.session.user)
			if outcome == APPROVED:
				self.add_comment("Info", _("Approved by {0}.").format(reviewer))
			else:
				self.add_comment("Info", _("Rejected by {0}. Reason: {1}").format(reviewer, self.rejection_reason))
			notify_employee(self, outcome)

	# --- reference -------------------------------------------------------
	def set_reference_details(self):
		self.employee = self.reference_name if self.reference_doctype == "Employee" else None
		self.reference_title = get_reference_title(self.reference_doctype, self.reference_name)

	def validate_reference_access(self):
		if not frappe.db.exists(self.reference_doctype, self.reference_name):
			frappe.throw(_("{0} {1} does not exist").format(_(self.reference_doctype), self.reference_name))
		if has_unrestricted_role():
			return
		if self.employee:
			if self.get_linked_user() != frappe.session.user:
				frappe.throw(_("You can only add documents to your own employee record."), frappe.PermissionError)
		elif not frappe.has_permission(self.reference_doctype, "read", doc=self.reference_name):
			frappe.throw(_("You do not have access to {0} {1}").format(_(self.reference_doctype), self.reference_name),
			             frappe.PermissionError)

	def validate_dates(self):
		# Document Type Master decides which dates are shown (fetched to *_required) and mandatory;
		# checked here too, as the form's mandatory_depends_on is not enforced by the server
		rules = frappe.db.get_value(
			"Document Type Master", self.document_type,
			["issue_date_required", "issue_date_mandatory", "expiry_required", "expiry_date_mandatory"],
			as_dict=True,
		) or {}
		for date_field, required, mandatory, label in (
			("issue_date", "issue_date_required", "issue_date_mandatory", _("Issue Date")),
			("expiry_date", "expiry_required", "expiry_date_mandatory", _("Expiry Date")),
		):
			self.set(required, cint(rules.get(required)))
			self.set(mandatory, cint(rules.get(required)) and cint(rules.get(mandatory)))
			if self.get(mandatory) and not self.get(date_field):
				frappe.throw(
					_("{0} is mandatory for {1}.").format(label, frappe.bold(self.document_type)),
					frappe.MandatoryError,
					title=_("Missing {0}").format(label),
				)
		if self.issue_date and getdate(self.issue_date) > getdate(today()):
			frappe.throw(
				_("Issue Date {0} cannot be in the future.").format(frappe.format(self.issue_date, "Date")),
				title=_("Invalid Issue Date"),
			)
		# checked when the Expiry Date is entered or changed, so a document that has since expired
		# can still be edited (e.g. its remarks)
		if (
			self.expiry_date
			and (self.is_new() or self.has_value_changed("expiry_date"))
			and getdate(self.expiry_date) < getdate(today())
		):
			frappe.throw(
				_("Expiry Date {0} cannot be in the past.").format(frappe.format(self.expiry_date, "Date")),
				title=_("Invalid Expiry Date"),
			)
		if self.issue_date and self.expiry_date and getdate(self.expiry_date) <= getdate(self.issue_date):
			frappe.throw(
				_("Expiry Date must be after the Issue Date."),
				title=_("Invalid Expiry Date"),
			)

	def get_linked_user(self):
		if not self.employee:
			return None
		if self.flags.linked_user is None:
			self.flags.linked_user = frappe.db.get_value("Employee", self.employee, "user_id") or ""
		return self.flags.linked_user or None

	def is_linked_user(self, user=None):
		linked = self.get_linked_user()
		return bool(linked) and linked == (user or frappe.session.user)

	# --- approval status ------------------------------------------------
	def content_changed(self):
		if self.is_new():
			return True
		before = self.get_doc_before_save()
		if not before:
			return True
		if _files(self) != _files(before):
			return True
		return any(_norm(self.get(f)) != _norm(before.get(f)) for f in CONTENT_FIELDS)

	def restore_approval_fields(self):
		before = None if self.is_new() else self.get_doc_before_save()
		for f in APPROVAL_FIELDS:
			self.set(f, before.get(f) if before else None)

	def set_approval_status(self):
		if not self.content_changed():
			return
		user = frappe.session.user
		is_new = self.is_new()
		previous = None if is_new else self.approval_status

		if self.is_linked_user(user):
			# The employee's own upload/edit: needs approval (even if they are an HR Manager)
			self.approval_status = PENDING
			self.submitted_by = user
			self.reviewed_by = None
			self.reviewed_on = None
			self.flags.notify_hr = previous != PENDING
			if is_new:
				self.flags.timeline_note = _("Uploaded by the employee. Waiting for HR Manager approval.")
			elif previous == REJECTED:
				self.flags.timeline_note = _("Corrected and resubmitted for approval.")
			elif previous == APPROVED:
				self.flags.timeline_note = _("Edited by the employee after approval. Sent back for approval.")
		else:
			# HR or any user not linked to this employee: auto-approved
			self.approval_status = APPROVED
			self.reviewed_by = user
			self.reviewed_on = now_datetime()
			self.rejection_reason = None
			if not self.submitted_by:
				self.submitted_by = user
			if previous in (PENDING, REJECTED):
				self.flags.timeline_note = _("Auto-approved: updated by {0}.").format(get_fullname(user))

	# --- approve / reject (Review buttons, or Approval Status set in the form) ---
	def can_review(self, user=None):
		user = user or frappe.session.user
		return (
			self.approval_status == PENDING
			and APPROVER_ROLE in frappe.get_roles(user)
			and not self.is_linked_user(user)
			and self.submitted_by != user
		)

	def check_can_review(self):
		if self.approval_status != PENDING:
			frappe.throw(_("Only documents with status Pending Approval can be approved or rejected."))
		if APPROVER_ROLE not in frappe.get_roles():
			frappe.throw(_("Only an HR Manager can approve or reject documents."), frappe.PermissionError)
		user = frappe.session.user
		if self.is_linked_user(user) or self.submitted_by == user:
			frappe.throw(_("You cannot approve or reject your own document."), frappe.PermissionError)

	def get_review_request(self):
		"""(status, reason) when an HR Manager changed Approval Status of a pending document in
		the form. Anyone else's change is ignored: restore_approval_fields puts the value back."""
		if self.is_new() or self.approval_status not in (APPROVED, REJECTED):
			return None
		before = self.get_doc_before_save()
		if not before or before.approval_status != PENDING:
			return None
		# checked on the saved document: submitted_by from the browser is not trusted
		if not before.can_review():
			return None
		return self.approval_status, (self.rejection_reason or "").strip()

	def apply_review(self, status, reason=None):
		reason = (reason or "").strip()
		if status == REJECTED and not reason:
			frappe.throw(_("Please enter a reason for rejection."), title=_("Rejection Reason Required"))
		self.approval_status = status
		self.reviewed_by = frappe.session.user
		self.reviewed_on = now_datetime()
		self.rejection_reason = reason if status == REJECTED else None
		self.flags.review_outcome = status  # comment + employee notification in on_update

	@frappe.whitelist()
	def approve(self):
		self.check_can_review()
		self.apply_review(APPROVED)
		self.flags.approval_action = True
		self.save()

	@frappe.whitelist()
	def reject(self, reason=None):
		self.check_can_review()
		self.apply_review(REJECTED, reason)
		self.flags.approval_action = True
		self.save()


# --- small helpers -------------------------------------------------------
def _norm(value):
	return "" if value in (None, "") else str(value)


def _files(doc):
	return [(row.file or "", row.description or "") for row in doc.get("attachments") or []]


def has_unrestricted_role(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(UNRESTRICTED_ROLES & set(frappe.get_roles(user)))


def get_reference_title(doctype, name):
	if not (doctype and name):
		return None
	title_field = frappe.get_meta(doctype).get_title_field()
	if title_field and title_field != "name":
		return frappe.db.get_value(doctype, name, title_field) or name
	return name


def is_inactive_employee(employee):
	return bool(employee) and frappe.db.get_value("Employee", employee, "status") in INACTIVE_EMPLOYEE_STATUSES


# --- notifications (bell + email) ----------------------------------------
def get_hr_managers():
	users = frappe.get_all("Has Role", filters={"role": APPROVER_ROLE, "parenttype": "User"},
	                       pluck="parent", distinct=True)
	if not users:
		return []
	return frappe.get_all("User", filters={"name": ["in", users], "enabled": 1, "user_type": "System User"},
	                      pluck="name")


def email_configured():
	"""True when Frappe has somewhere to send email from."""
	return bool(
		frappe.conf.get("mail_server")
		or frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1})
	)


def has_unread_notification(user, subject, doc):
	return frappe.db.exists("Notification Log", {
		"for_user": user, "document_type": doc.doctype, "document_name": doc.name,
		"subject": subject, "read": 0,
	})


def send_notification(users, subject, message, doc, skip_unread_duplicates=False):
	"""Bell + email, once per user. With skip_unread_duplicates, a user who still has the same
	unread notification for this document is skipped (ClickUp 14yr2e57q0t)."""
	users = sorted({u for u in users if u and u not in ("Administrator", "Guest")})
	if skip_unread_duplicates:
		users = [u for u in users if not has_unread_notification(u, subject, doc)]
	if not users:
		return
	for user in users:
		frappe.get_doc({
			"doctype": "Notification Log", "for_user": user, "from_user": frappe.session.user,
			"type": "Alert", "document_type": doc.doctype, "document_name": doc.name,
			"subject": subject, "email_content": message,
		}).insert(ignore_permissions=True)
	# "Alert" notifications never email by themselves in v16, so send the email here,
	# but only when an outgoing email account exists (otherwise saving the document would fail)
	if email_configured():
		emails = sorted({e for e in frappe.get_all("User", filters={"name": ["in", users]}, pluck="email") if e})
		for email in emails:
			send_email(email, subject, message, doc)


def send_email(email, subject, message, doc):
	"""One Email Queue per recipient, owned by Administrator (ClickUp 14yr2e57q0t).
	A shared queue is retried as a whole (Email Retry Limit, 3 by default) when one address
	fails, which can deliver the same email up to four times. When it finally fails, Frappe
	puts "Failed to send email with subject: ..." in the bell of the queue's owner: that would
	be the HR Manager who approved, or the employee who uploaded, instead of the recipient."""
	queue = frappe.sendmail(
		recipients=[email], subject=frappe.utils.strip_html(subject),
		message=f"<p>{message}</p><p>{get_link_to_form(doc.doctype, doc.name)}</p>",
		reference_doctype=doc.doctype, reference_name=doc.name,
	)
	if queue and getattr(queue, "name", None):
		frappe.db.set_value("Email Queue", queue.name, "owner", "Administrator", update_modified=False)


def notify_hr_managers(doc):
	recipients = [u for u in get_hr_managers() if u != frappe.session.user]
	subject = _("{0} needs approval: {1} for {2}").format(doc.name, doc.document_type, doc.reference_title)
	message = _("{0} uploaded or changed a {1} document for {2}. Please review and approve or reject it.").format(
		get_fullname(frappe.session.user), doc.document_type, doc.reference_title)
	# an HR Manager who has not opened the earlier request yet is not told again
	send_notification(recipients, subject, message, doc, skip_unread_duplicates=True)


def notify_employee(doc, outcome):
	"""Only the employee the document belongs to: never the HR Manager who reviewed it."""
	recipient = doc.get_linked_user() or doc.submitted_by
	if not recipient or recipient == frappe.session.user:
		return
	if outcome == APPROVED:
		subject = _("Your {0} document has been approved").format(doc.document_type)
		message = _("{0} approved your {1} document ({2}).").format(
			get_fullname(frappe.session.user), doc.document_type, doc.name)
	else:
		subject = _("Your {0} document has been rejected").format(doc.document_type)
		message = _("{0} rejected your {1} document ({2}). Reason: {3}. Please correct it and save to resubmit.").format(
			get_fullname(frappe.session.user), doc.document_type, doc.name, doc.rejection_reason)
	send_notification([recipient], subject, message, doc)


# --- permissions (registered in hooks.py) --------------------------------
def get_permission_query_conditions(user=None):
	"""List filter: hide documents of Inactive/Left employees; limit what non-HR users see."""
	user = user or frappe.session.user
	table = f"`tab{DOCTYPE}`"
	statuses = ", ".join(frappe.db.escape(s) for s in INACTIVE_EMPLOYEE_STATUSES)
	conditions = [
		f"(ifnull({table}.employee, '') = '' or not exists (select 1 from `tabEmployee` emp "
		f"where emp.name = {table}.employee and emp.status in ({statuses})))"
	]
	if has_unrestricted_role(user):
		return " and ".join(conditions)

	allowed = []
	own_employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
	if own_employees:
		allowed.append(f"{table}.employee in ({', '.join(frappe.db.escape(e) for e in own_employees)})")
	reference_doctypes = frappe.get_all(DOCTYPE, fields=["reference_doctype"], distinct=True, pluck="reference_doctype")
	readable = [dt for dt in reference_doctypes
	            if dt and dt != "Employee" and frappe.has_permission(dt, "read", user=user)]
	if readable:
		allowed.append(f"{table}.reference_doctype in ({', '.join(frappe.db.escape(dt) for dt in readable)})")
	conditions.append(f"({' or '.join(allowed)})" if allowed else "1=0")
	return " and ".join(conditions)


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Single document: employee documents only for HR and that employee; others follow
	the user's access to the record the document belongs to."""
	user = user or frappe.session.user
	if has_unrestricted_role(user):
		return True
	if doc.reference_doctype == "Employee" or doc.get("employee"):
		if not doc.reference_name:
			return True
		return frappe.db.get_value("Employee", doc.reference_name, "user_id") == user
	if doc.reference_doctype and doc.reference_name:
		ref_ptype = "write" if ptype in ("write", "create", "delete") else "read"
		return frappe.has_permission(doc.reference_doctype, ref_ptype, doc=doc.reference_name, user=user)
	return True


# --- daily expiry alerts (registered in hooks.py) ------------------------
def send_expiry_alerts():
	"""Daily. Only Approved documents of active employees; Pending / Rejected are ignored. Every
	document with an Expiry Date counts, also when its type has Expiry Date switched off
	(ClickUp 14yr2e57cqm).

	- Advance alert, once per Expiry Date: the first run on which the document is inside its type's
	  alert window (Days Before Expiry to Alert, default 30) sends "expires in N days". Normally that
	  is exactly N days before; a document added, approved or dated later, when the window has
	  already started, is alerted on the next run instead of only on its expiry day.
	  expiry_alert_sent_for remembers the Expiry Date alerted, so a renewed document (new date) is
	  alerted again in its next window.
	- On the expiry day: "expires today".
	"""
	run_date = getdate(today())
	types = frappe.get_all("Document Type Master", filters={"disabled": 0}, fields=["name", "alert_days_before"])
	hr_managers = get_hr_managers()
	for doc_type in types:
		days = cint(doc_type.alert_days_before) or 30
		for row in frappe.get_all(
			DOCTYPE,
			filters={
				"document_type": doc_type.name,
				"approval_status": APPROVED,
				"expiry_date": ["between", [run_date, add_days(run_date, days)]],
			},
			fields=["name", "expiry_date", "expiry_alert_sent_for"],
		):
			expiry = getdate(row.expiry_date)
			alerted = row.expiry_alert_sent_for and getdate(row.expiry_alert_sent_for) == expiry
			if expiry != run_date and alerted:
				continue
			doc = frappe.get_doc(DOCTYPE, row.name)
			if is_inactive_employee(doc.employee):
				continue
			send_expiry_alert(doc, (expiry - run_date).days, hr_managers)
			if not alerted:
				doc.db_set("expiry_alert_sent_for", expiry, update_modified=False)


def send_expiry_alert(doc, days_left, hr_managers):
	"""HR reads "Driving License for Simna Jose expires today"; Simna Jose herself reads "Your
	Driving License expires today" (no own name), also when she is an HR Manager."""
	expiry_on = frappe.utils.formatdate(doc.expiry_date)
	number = doc.card_number or doc.name
	employee_user = doc.get_linked_user()

	if days_left <= 0:
		subject = _("{0} for {1} expires today").format(doc.document_type, doc.reference_title)
		own_subject = _("Your {0} expires today").format(doc.document_type)
	elif days_left == 1:
		subject = _("{0} for {1} expires tomorrow").format(doc.document_type, doc.reference_title)
		own_subject = _("Your {0} expires tomorrow").format(doc.document_type)
	else:
		subject = _("{0} for {1} expires in {2} days").format(doc.document_type, doc.reference_title, days_left)
		own_subject = _("Your {0} expires in {1} days").format(doc.document_type, days_left)
	message = _("{0} ({1}) for {2} expires on {3}.").format(doc.document_type, number, doc.reference_title, expiry_on)
	own_message = _("Your {0} ({1}) expires on {2}. Please renew it and upload the new document.").format(
		doc.document_type, number, expiry_on)

	send_notification([u for u in hr_managers if u != employee_user], subject, message, doc)
	if employee_user:
		send_notification([employee_user], own_subject, own_message, doc)


# --- approve / reject from other pages (Employee Documents section) -------
@frappe.whitelist()
def review_document(name, action, reason=None):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	if action == "approve":
		doc.approve()
	elif action == "reject":
		doc.reject(reason)
	else:
		frappe.throw(_("Invalid action."))
	return doc.approval_status


@frappe.whitelist()
def get_files(names: list[str] | str) -> dict:
	"""Files of the given documents, for the Employee Documents section (only documents the user may read)."""
	names = frappe.parse_json(names) if isinstance(names, str) else names
	allowed = frappe.get_list(DOCTYPE, filters={"name": ["in", names or []]}, pluck="name")
	files = {}
	for row in frappe.get_all(
		"Document Attachment",
		filters={"parenttype": DOCTYPE, "parent": ["in", allowed or [""]]},
		fields=["parent", "file", "description"],
		order_by="idx asc",
	):
		files.setdefault(row.parent, []).append({"file": row.file, "description": row.description})
	return files


# Documents every new employee must upload (Document Type Master > Mandatory at Joining, optionally
# only for one Nationality). ClickUp 14yr2e57mhp. Shown in the Employee Documents section.
MISSING = "Missing"
# the best document of a type decides its status: an approved one beats a pending one, etc.
STATUS_RANK = {APPROVED: 3, PENDING: 2, REJECTED: 1}


def mandatory_document_types(nationality=None):
	"""Enabled document types mandatory at joining for an employee of `nationality`."""
	types = frappe.get_all(
		"Document Type Master",
		filters={"disabled": 0, "mandatory_at_joining": 1},
		fields=["name", "mandatory_for_nationality"],
		order_by="name asc",
	)
	return [t.name for t in types if not t.mandatory_for_nationality or t.mandatory_for_nationality == nationality]


def mandatory_document_status(employee):
	"""[{document_type, status, document}] for each mandatory type: Missing, or the status of the
	employee's best document of that type (Approved > Pending Approval > Rejected)."""
	nationality = frappe.db.get_value("Employee", employee, "alt_nationality")
	required = mandatory_document_types(nationality)
	best = {}
	for doc in frappe.get_all(
		DOCTYPE,
		filters={"reference_doctype": "Employee", "reference_name": employee, "document_type": ["in", required or [""]]},
		fields=["name", "document_type", "approval_status"],
		order_by="creation desc",
	):
		doc.approval_status = doc.approval_status or APPROVED  # uploaded before the approval flow
		rank = STATUS_RANK.get(doc.approval_status, 0)
		if rank > best.get(doc.document_type, (0, None))[0]:
			best[doc.document_type] = (rank, doc)
	rows = []
	for document_type in required:
		doc = best.get(document_type, (0, None))[1]
		rows.append(
			{
				"document_type": document_type,
				"status": doc.approval_status if doc else MISSING,
				"document": doc.name if doc else None,
			}
		)
	return rows


@frappe.whitelist()
def get_mandatory_documents(employee: str):
	"""Employee Documents section: the mandatory documents and whether each is uploaded."""
	frappe.has_permission("Employee", "read", employee, throw=True)
	return mandatory_document_status(employee)

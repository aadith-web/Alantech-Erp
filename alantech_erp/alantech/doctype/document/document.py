import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_fullname, get_link_to_form, getdate, now_datetime, today

DOCTYPE = "Document"
APPROVER_ROLE = "HR Manager"
UNRESTRICTED_ROLES = {"System Manager", "HR Manager", "HR User"}
INACTIVE_EMPLOYEE_STATUSES = ("Inactive", "Left")
PENDING, APPROVED, REJECTED = "Pending Approval", "Approved", "Rejected"

# Set only by the server, never accepted from the browser
APPROVAL_FIELDS = ("approval_status", "submitted_by", "reviewed_by", "reviewed_on", "rejection_reason")
# A change to any of these counts as an edit
CONTENT_FIELDS = ("reference_doctype", "reference_name", "document_type", "card_number", "issue_date",
                  "place_of_issue", "expiry_date", "issuing_country", "attachment", "remarks")


class Document(Document):
	def validate(self):
		self.set_reference_details()
		self.validate_reference_access()
		self.validate_dates()
		if self.flags.approval_action:      # approve()/reject() set the fields themselves
			return
		self.restore_approval_fields()
		self.set_approval_status()

	def on_update(self):
		if self.flags.timeline_note:
			self.add_comment("Info", self.flags.timeline_note)   # shows in Activity Log
		if self.flags.notify_hr:
			notify_hr_managers(self)

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
		if self.issue_date and getdate(self.issue_date) > getdate(today()):
			frappe.throw(
				_("Issue Date {0} cannot be in the future.").format(frappe.format(self.issue_date, "Date")),
				title=_("Invalid Issue Date"),
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

	# --- approve / reject (called from the Review buttons) ---------------
	def check_can_review(self):
		if self.approval_status != PENDING:
			frappe.throw(_("Only documents with status Pending Approval can be approved or rejected."))
		if APPROVER_ROLE not in frappe.get_roles():
			frappe.throw(_("Only an HR Manager can approve or reject documents."), frappe.PermissionError)
		user = frappe.session.user
		if self.is_linked_user(user) or self.submitted_by == user:
			frappe.throw(_("You cannot approve or reject your own document."), frappe.PermissionError)

	@frappe.whitelist()
	def approve(self):
		self.check_can_review()
		self.approval_status = APPROVED
		self.reviewed_by = frappe.session.user
		self.reviewed_on = now_datetime()
		self.rejection_reason = None
		self.flags.approval_action = True
		self.save()
		self.add_comment("Info", _("Approved by {0}.").format(get_fullname(frappe.session.user)))
		notify_employee(self, APPROVED)

	@frappe.whitelist()
	def reject(self, reason=None):
		self.check_can_review()
		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("Please enter a reason for rejection."))
		self.approval_status = REJECTED
		self.reviewed_by = frappe.session.user
		self.reviewed_on = now_datetime()
		self.rejection_reason = reason
		self.flags.approval_action = True
		self.save()
		self.add_comment("Info", _("Rejected by {0}. Reason: {1}").format(get_fullname(frappe.session.user), reason))
		notify_employee(self, REJECTED)


# --- small helpers -------------------------------------------------------
def _norm(value):
	return "" if value in (None, "") else str(value)


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


def send_notification(users, subject, message, doc):
	users = sorted({u for u in users if u and u not in ("Administrator", "Guest")})
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
	emails = [e for e in frappe.get_all("User", filters={"name": ["in", users]}, pluck="email") if e]
	if emails and email_configured():
		frappe.sendmail(recipients=emails, subject=frappe.utils.strip_html(subject),
		                message=f"<p>{message}</p><p>{get_link_to_form(doc.doctype, doc.name)}</p>",
		                reference_doctype=doc.doctype, reference_name=doc.name)


def notify_hr_managers(doc):
	recipients = [u for u in get_hr_managers() if u != frappe.session.user]
	subject = _("{0} needs approval: {1} for {2}").format(doc.name, doc.document_type, doc.reference_title)
	message = _("{0} uploaded or changed a {1} document for {2}. Please review and approve or reject it.").format(
		get_fullname(frappe.session.user), doc.document_type, doc.reference_title)
	send_notification(recipients, subject, message, doc)


def notify_employee(doc, outcome):
	recipient = doc.submitted_by or doc.get_linked_user()
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
	"""Only Approved documents count; Pending/Rejected are ignored."""
	run_date = getdate(today())
	types = frappe.get_all("Document Type Master", filters={"disabled": 0, "expiry_required": 1},
	                       fields=["name", "alert_days_before"])
	hr_managers = get_hr_managers()
	for doc_type in types:
		days = cint(doc_type.alert_days_before) or 30
		names = frappe.get_all(DOCTYPE, filters={
			"document_type": doc_type.name, "approval_status": APPROVED,
			"expiry_date": ["in", [add_days(run_date, days), run_date]],
		}, pluck="name")
		for name in names:
			doc = frappe.get_doc(DOCTYPE, name)
			if is_inactive_employee(doc.employee):
				continue
			if getdate(doc.expiry_date) == run_date:
				subject = _("{0} for {1} expires today").format(doc.document_type, doc.reference_title)
			else:
				subject = _("{0} for {1} expires in {2} days").format(doc.document_type, doc.reference_title, days)
			message = _("{0} ({1}) for {2} expires on {3}.").format(
				doc.document_type, doc.card_number or doc.name, doc.reference_title,
				frappe.utils.formatdate(doc.expiry_date))
			send_notification([*hr_managers, doc.get_linked_user()], subject, message, doc)

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
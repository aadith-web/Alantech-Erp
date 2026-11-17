app_name = "alantech_erp"
app_title = "AlanTech"
app_publisher = "JincyTricta"
app_description = "ERP Platform"
app_email = "jincy@tricta.com"
app_license = "mit"
app_logo_url = "/assets/alantech_erp/images/alantech-logo.png"
# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "AlanTech ERP",
# 		# "logo": "/assets/crm/images/logo.svg",
# 		"title": "AlanTech ERP",
# 		"route": "/core",
# 	}
# ]

website_context = {
	"footer_powered": "AlanTech ERP",
	"favicon": "/assets/alantech_erp/images/alantech-favicon.png",
	"splash_image": "/assets/alantech_erp/images/alantech-logo.png",
	"banner_image": "/assets/alantech_erp/images/alantech-logo.png",
	"navbar_logo": "/assets/alantech_erp/images/alantech-logo.png",
}

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = [
	"/assets/alantech_erp/css/alantech_tokens.css",
	"/assets/alantech_erp/css/alantech_desk.css",
        "/assets/alantech_erp/js/alantech_documents.js",
]
# app_include_js = "/assets/alantech_erp/js/alantech_erp.js"
app_include_js = [
    # country code picker of Phone fields opens on saved records too
    "/assets/alantech_erp/js/phone_control.js",
    # Customer quick entry: Tax Type Local -> GSTIN and the address fields are mandatory
    "/assets/alantech_erp/js/customer_quick_entry.js",
    # Home page check-in reminder popup (HR-F02)
    "/assets/alantech_erp/js/checkin_reminder.js",
    # bell: a notification viewed is marked read, count kept right (ClickUp 14yr2e57yr3)
    "/assets/alantech_erp/js/notification_read.js",
    # Activity menu + Activities panel on Lead, Customer and Deal (CRM C10, sales/activity.py)
    "/assets/alantech_erp/js/sales_activity.js",
    # Lending forms: employee name under the Applicant box (loan_rules/loan.get_applicant_name)
    "/assets/alantech_erp/js/loan_applicant_name.js",
]

# include js, css files in header of web template
web_include_css = [
	"/assets/alantech_erp/css/alantech_tokens.css",
	"/assets/alantech_erp/css/alantech_web.css",
]
# web_include_js = "/assets/alantech_erp/js/alantech_web.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "alantech_erp/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}
doctype_js = {
    "Employee": "public/js/employee.js",
    "Lead": "public/js/lead.js",
    "Opportunity": "public/js/opportunity.js",
    "Quotation": "public/js/quotation.js",
    "Customer": "public/js/customer.js",
    # live cost sheet calculation of the Estimation form
    "Estimation": "public/js/estimation_pricing.js",
    # approver lookup without an employee yet (Frappe v16 link validation)
    "Shift Request": "public/js/shift_request.js",
    # view-only Holiday List for employees
    "Holiday List": "public/js/holiday_list.js",
    # one summary of the users created by an Employee import
    "Data Import": "public/js/data_import.js",
    # asterisk on collection offset sequences Lending requires when the Company has none
    "Loan Product": "public/js/loan_product.js",
    # Loan Eligibility check list rendered as a table, not raw HTML text
    "Loan Application": "public/js/loan_application.js",
    # hides Create > Loan Disbursement from users who cannot disburse
    "Loan": "public/js/loan.js",
    "Employee Checkin": "public/js/employee_checkin.js",
    # Campaign owner, budget, costs, child campaigns and results (CRM C36)
    "Campaign": "public/js/campaign.js",
}
extend_doctype_class = {
    # "Create User Automatically" without an email: no user, no error (setup/employee_user.py)
    "Employee": "alantech_erp.setup.employee_user.AlantechEmployee",
}
# Employee import summary (setup/employee_user.py): Employee.on_update clears the whole cache
persistent_cache_keys = ["alt_employee_import_notes|*"]
doctype_list_js = {
    "Employee": "public/js/employee_list.js",
    "Holiday List Assignment": "public/js/holiday_list_assignment_list.js",
    # Add Loan lists the Approved Loan Applications without a Loan (HR-F05-x)
    "Loan": "public/js/loan_list.js",
    # Add Loan Disbursement lists the Sanctioned loans waiting to be paid out (HR-F05-x)
    "Loan Disbursement": "public/js/loan_disbursement_list.js",
    "Employee Checkin": "public/js/employee_checkin_list.js",
}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "alantech_erp/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

jinja = {
    # print formats Alantech Technical Offer / Alantech Proposal / Alantech Cost Sheet
    "methods": [
        "alantech_erp.proposal.printing.get_offer_context",
        "alantech_erp.proposal.printing.get_cost_sheet_context",
    ],
}

# Installation
# ------------

# before_install = "alantech_erp.install.before_install"
# after_install = "alantech_erp.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "alantech_erp.uninstall.before_uninstall"
# after_uninstall = "alantech_erp.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "alantech_erp.utils.before_app_install"
# after_app_install = "alantech_erp.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "alantech_erp.utils.before_app_uninstall"
# after_app_uninstall = "alantech_erp.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "alantech_erp.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["alantech_erp.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# Sales records by the Sales Person tree (alantech_erp/sales/hierarchy.py): engineers see their
# own, managers their team's, the Sales Director everything
_SALES_HIERARCHY = "alantech_erp.sales.hierarchy"
permission_query_conditions = {
    "Document": "alantech_erp.alantech.doctype.document.document.get_permission_query_conditions",
	"Session Log": "alantech_erp.alantech.doctype.session_log.session_log.get_permission_query_conditions",
	"Holiday List": "alantech_erp.setup.shifts.holiday_list_query_conditions",
	"Company Policy": "alantech_erp.alantech.doctype.company_policy.company_policy.get_permission_query_conditions",
	# Employee Loan Rules (LR-09): employees see only their own loan applications and loans
	"Loan Application": "alantech_erp.setup.loan_permissions.loan_application_query_conditions",
	"Loan": "alantech_erp.setup.loan_permissions.loan_query_conditions",
	"Salary Structure Assignment": "alantech_erp.setup.salary_access.salary_structure_assignment_query_conditions",
	"Salary Slip": "alantech_erp.setup.salary_access.salary_slip_query_conditions",
	"Lead": f"{_SALES_HIERARCHY}.lead_query",
	"Customer": f"{_SALES_HIERARCHY}.customer_query",
	"Opportunity": f"{_SALES_HIERARCHY}.opportunity_query",
	"Estimation": f"{_SALES_HIERARCHY}.estimation_query",
	"Technical Offer": f"{_SALES_HIERARCHY}.technical_offer_query",
	"Quotation": f"{_SALES_HIERARCHY}.quotation_query",
	"Sales Order": f"{_SALES_HIERARCHY}.sales_order_query",
	"Sales Activity": f"{_SALES_HIERARCHY}.sales_activity_query",
	# a Sales Engineer / Manager sees the forecasts of their own part of the tree
	"Sales Forecast": "alantech_erp.sales.forecast.sales_forecast_query",
	# HR imports employees: only imports into doctypes the user may import
	"Data Import": "alantech_erp.setup.data_import_permissions.get_permission_query_conditions",
	# employees see only their own notice period
	"Employee Notice Period": "alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period.get_permission_query_conditions",
}
has_permission = {
	"Document": "alantech_erp.alantech.doctype.document.document.has_permission",
	"Session Log": "alantech_erp.alantech.doctype.session_log.session_log.has_permission",
	"Holiday List": "alantech_erp.setup.shifts.holiday_list_has_permission",
	"Company Policy": "alantech_erp.alantech.doctype.company_policy.company_policy.has_permission",
	"Loan Application": "alantech_erp.setup.loan_permissions.has_permission",
	"Loan": "alantech_erp.setup.loan_permissions.has_permission",
	"Salary Structure Assignment": "alantech_erp.setup.salary_access.has_permission",
	"Salary Slip": "alantech_erp.setup.salary_access.has_permission",
	"Data Import": "alantech_erp.setup.data_import_permissions.has_permission",
	"Employee Notice Period": "alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period.has_permission",
	**{
		doctype: f"{_SALES_HIERARCHY}.has_permission"
		for doctype in (
			"Lead", "Customer", "Opportunity", "Estimation", "Technical Offer", "Quotation", "Sales Order", "Sales Activity",
		)
	},
}
# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }
override_doctype_class = {
    # Employee import: unused rows of the Series-pre-filled template are skipped (setup/employee_import.py)
    "Data Import": "alantech_erp.setup.employee_import.AlantechDataImport",
}

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

fixtures = [
    {"dt": "Print Format", "filters": [["name", "in", ["Offer Letter", "Appointment Letter"]]]},
    {"dt": "Letter Head", "filters": [["name", "in", ["AlanTech"]]]},
    {"dt": "Custom Field", "or_filters": [
        ["fieldname", "like", "alt\\_%"],
        ["name", "in", [
          "Salary Detail-custom_overtime_hours",
          "Salary Detail-custom_ot_type",
          "Event-custom_call_type",
          "Event-custom_call_purpose",
          "Event-custom_call_result",
          "Event-custom_section_break_i4ir3",
          "Event-custom_section_break_fxv5g",
          "Employee-custom_ref_no",
          "Employee-custom_job_description",
          "Company-custom_hr_signatory_name",
          "Company-custom_hr_email",
          "Company-custom_hr_office_address",
        ]],
    ]},
    {"dt": "Property Setter", "or_filters": [
        ["name", "like", "%alt\\_%"],
        ["name", "=", "Event-main-field_order"],
    ]},
    {"dt": "Workflow"},
    {"dt": "Workflow State"},
    {"dt": "Workflow Action Master"},
    {"dt": "Role", "filters": [["name", "in", ["Proposal Engineer", "Design Engineer", "Quotation Level 2 Approver"]]]},
    {"dt": "Designation"},
    {"dt": "Department", "filters": [["name", "!=", "All Departments"]]},
    {"dt": "Document Type Master"}
    
]

doc_events = {
    # Loan Management flow (HR-F05-x): an HR Manager is also a Loan Manager
    "User": {"validate": "alantech_erp.setup.loan_roles.user_validate"},
    # new Loan Products get the employee loan ledgers for accounts left blank (HR-F05-x)
    "Loan Product": {"before_insert": "alantech_erp.setup.loan_accounts.loan_product_before_insert"},
    # a Loan is made only from an Approved Loan Application (HR-F05-x)
    "Loan": {"validate": "alantech_erp.loan_rules.loan.validate"},
    # Employee Loan Rules: match the Loan Rule, run the checks, block / warn / override (LR-03, LR-05)
    "Loan Application": {
        "before_validate": "alantech_erp.loan_rules.loan_application.before_validate",
        "validate": "alantech_erp.loan_rules.loan_application.validate",
        "before_submit": "alantech_erp.loan_rules.loan_application.before_submit",
        "before_update_after_submit": "alantech_erp.loan_rules.loan_application.before_update_after_submit",
        "on_update": "alantech_erp.loan_rules.loan_application.on_update",
        "on_update_after_submit": "alantech_erp.loan_rules.loan_application.on_update_after_submit",
    },
    # a Stock Entry made by an Employee Uniform Issue is cancelled through that issue only
    "Stock Entry": {
        "before_cancel": "alantech_erp.alantech.doctype.employee_uniform_issue.employee_uniform_issue.stock_entry_before_cancel",
    },
    "Employee": {
        "before_insert": [
            # blank Employee Number (form or Data Import) -> next E### number
            "alantech_erp.setup.employee_validation.set_employee_number",
            "alantech_erp.setup.employee_user.employee_before_insert",
        ],
        "after_insert": "alantech_erp.setup.employee_user.employee_after_insert",
        "validate": [
            "alantech_erp.org_structure.apply_designation_defaults",
            # Reports To: managers only (ClickUp 14yr2e57t0m)
            "alantech_erp.setup.reports_to.validate_reports_to",
            "alantech_erp.setup.employee_validation.validate_unique_employee",
            "alantech_erp.setup.employee_validation.validate_unique_email",
            "alantech_erp.setup.employee_validation.validate_mobile_number",
            # 18 or older on the Date of Joining
            "alantech_erp.setup.employee_validation.validate_minimum_age",
            "alantech_erp.setup.access.employee_validate",
            # after apply_designation_defaults, which may fill Reports To
            "alantech_erp.setup.approvers.employee_validate",
            "alantech_erp.setup.shifts.employee_holiday_list",
            # last: Department / Reports To may be filled from the designation above
            "alantech_erp.setup.employee_validation.validate_required_on_create",
            # Nationality (Citizen) on create, never cleared (ClickUp 14yr2e57r7h)
            "alantech_erp.setup.employee_nationality.validate_nationality",
            # Nationality India: Aadhaar + PAN mandatory; formats (ClickUp 14yr2e57r7k)
            "alantech_erp.setup.employee_nationality.validate_indian_ids",
            # blank Confirmation Date = Date of Joining + Probation Period (ClickUp 14yr2e57mhp)
            "alantech_erp.setup.employee_payroll_fields.fill_confirmation_date",
        ],
        "on_update": [
            "alantech_erp.org_structure.sync_user_role_profile",
            "alantech_erp.setup.access.employee_on_update",
            "alantech_erp.setup.approvers.employee_on_update",
            "alantech_erp.org_structure.fill_vacant_post",
            # alert HR when a resigning / leaving employee still holds assets
            "alantech_erp.alantech.doctype.employee_asset_handover.exit_alerts.employee_on_update",
            # Sales department employees get a linked Sales Person (alantech_erp.sales.sales_person)
            "alantech_erp.sales.sales_person.employee_on_update",
            "alantech_erp.setup.employee_fields.sync_user_employee_number",
            # changed Aadhaar / PAN -> the employee's Aadhaar / PAN documents (ClickUp 14yr2e57r7k)
            "alantech_erp.alantech.doctype.document.employee_numbers.update_documents",
            # new employee -> Employee Notice Period (default 30 days); Notice (days) kept in sync (ClickUp 14yr2e57r71)
            "alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period.employee_on_update",
        ],
        "on_trash": [
            "alantech_erp.sales.sales_person.employee_on_trash",
            "alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period.employee_on_trash",
        ],
    },
    "Employee Separation": {
        "after_insert": "alantech_erp.alantech.doctype.employee_asset_handover.exit_alerts.employee_separation_after_insert",
    },
    "HR Settings": {
        "on_update": "alantech_erp.setup.employee_fields.show_employee_number_in_list",
    },
    "Salary Slip": {
        "validate": [
            "alantech_erp.overtime_utils.add_overtime_components",
            # hand-made slip: employee payroll fields filled (setup/employee_payroll_fields.py)
            "alantech_erp.setup.employee_payroll_fields.salary_slip_validate",
        ],
    },
    # Employee Mandatory Fields part 2: no payroll for an employee missing payroll fields
    # (setup/employee_payroll_fields.py, ClickUp 14yr2e57mhp)
    "Salary Structure Assignment": {
        "before_submit": "alantech_erp.setup.employee_payroll_fields.salary_structure_assignment_before_submit",
    },
    "Payroll Entry": {
        "before_submit": "alantech_erp.setup.employee_payroll_fields.payroll_entry_before_submit",
    },
    "Holiday List Assignment": {
        "validate": "alantech_erp.setup.shifts.set_assignment_status",
        "before_cancel": "alantech_erp.setup.shifts.set_assignment_status",
        "on_submit": "alantech_erp.setup.shifts.sync_employee_holiday_lists",
        "on_cancel": "alantech_erp.setup.shifts.sync_employee_holiday_lists",
    },
    "File": {
        # Document files: PDF / JPG / PNG only, at most 5 MB (alantech/doctype/document/document_files.py)
        "validate": "alantech_erp.alantech.doctype.document.document_files.validate_file",
    },
    # Work Mode defaults; Regular Hours Per Day > 0 for Flexible Threshold (setup/shift_ot_fields.py)
    "Shift Type": {
        "validate": "alantech_erp.setup.shift_ot_fields.validate",
    },
    "Employee Checkin": {
        # IN/OUT must alternate; a missed check-out blocks the next punch (setup/checkin_validation.py)
        "validate": "alantech_erp.setup.checkin_validation.validate",
        "after_insert": "alantech_erp.alantech.doctype.session_log.builder.on_checkin",  # "On Check-out"
        # a punch edited later (Log Type set after saving, time / employee corrected) rebuilds too
        "on_update": "alantech_erp.alantech.doctype.session_log.builder.on_checkin_update",
    },
    "Leave Application": {
		"before_validate": "alantech_erp.setup.leave_workflow.leave_application_before_validate",
		"validate": "alantech_erp.setup.leave_validation.validate_leave_application",
	},
	"Leave Allocation": {
		"validate": "alantech_erp.setup.leave_validation.validate_leave_allocation",
	},
	"Attendance Request": {
		"before_submit": "alantech_erp.setup.attendance_request.check_approver",  # own Leave Approver or HR
	},
    # CRM-F04 Customer Creation Management
    # Customer Type / Tax Type / lifecycle rules (alantech_erp/sales/customer.py); mobile, email,
    # GSTIN and name duplicates (alantech_erp/sales/customer_unique.py)
    "Customer": {
        "before_validate": [
            # Campaign of the Lead the customer was made from (CRM C24, sales/campaign.py)
            "alantech_erp.sales.campaign.customer_before_validate",
            "alantech_erp.sales.customer.before_validate",
            "alantech_erp.sales.customer_unique.before_validate",
        ],
        "validate": [
            "alantech_erp.sales.customer_unique.validate",
            "alantech_erp.sales.customer.validate",
        ],
        "onload": "alantech_erp.sales.customer.onload",
    },
    # a customer's contact cannot take another customer's mobile / email
    "Contact": {
        "validate": "alantech_erp.sales.customer_unique.contact_validate",
        "on_update": "alantech_erp.sales.customer_unique.contact_on_update",
    },
    # Local customer: billing address in India; Overseas: outside India
    "Address": {
        "validate": "alantech_erp.sales.customer.address_validate",
    },
    # Deal: no Prospect; Sales Stage follows the quotation (alantech_erp/sales/deal.py)
    "Opportunity": {
        "validate": [
            "alantech_erp.sales.deal.validate_opportunity",
            # Forecast Category / probability from the Sales Stage, Sales Person from the owner
            "alantech_erp.sales.forecast.opportunity_validate",
            # Campaign from the Quotation / party (CRM C24)
            "alantech_erp.sales.campaign.opportunity_validate",
        ],
        # a won Deal credits commission (basis Opportunity); re-opened / lost: reversed
        "on_update": "alantech_erp.sales.forecast.opportunity_on_update",
    },
    # Prospect flow not used (alantech_erp/sales/prospect.py)
    "Prospect": {
        "before_insert": "alantech_erp.sales.prospect.before_insert",
    },
    # Sales flow: Lead -> Customer -> Estimation -> Quotation (manager + client approval) -> Sales Order
    "Quotation": {
        "validate": [
            "alantech_erp.sales.quotation.validate",
            # Campaign from the Estimation / Deal / Customer (CRM C24)
            "alantech_erp.sales.campaign.quotation_validate",
        ],
        "before_submit": "alantech_erp.sales.quotation.before_submit",
        "before_update_after_submit": "alantech_erp.sales.quotation.before_update_after_submit",
        "on_update_after_submit": "alantech_erp.sales.quotation.on_update_after_submit",
        # tell the salesperson when the quotation is approved / rejected
        "on_change": "alantech_erp.sales.quotation.on_change",
    },
    "Sales Order": {
        "validate": [
            "alantech_erp.sales.sales_order.validate",
            # empty Sales Team: the quotation's Sales Person at 100% (forecast + commission credit)
            "alantech_erp.sales.commission.fill_sales_team",
            # Campaign from the Quotation / Customer (CRM C24)
            "alantech_erp.sales.campaign.sales_order_validate",
        ],
        "before_submit": "alantech_erp.sales.sales_order.before_submit",
        "on_submit": [
            "alantech_erp.sales.sales_order.on_submit",
            # the campaign's Income / ROI (CRM C36)
            "alantech_erp.sales.campaign.sales_order_changed",
            "alantech_erp.sales.commission.on_sales_order_submit",
            # the order's Deals are won (forecast Closed Won from Opportunity, Deal commission)
            "alantech_erp.sales.forecast.close_deals_won",
        ],
        "on_cancel": [
            "alantech_erp.sales.sales_order.on_cancel",
            "alantech_erp.sales.commission.on_cancel",
            "alantech_erp.sales.forecast.reopen_deals",
            "alantech_erp.sales.campaign.sales_order_changed",
        ],
    },
    # Sales activities (CRM C10, sales/activity.py): emails and comments on a Lead / Customer / Deal
    # are logged as activities; closing an activity's ToDo completes it
    "Communication": {"after_insert": "alantech_erp.sales.activity.communication_after_insert"},
    "Comment": {"after_insert": "alantech_erp.sales.activity.comment_after_insert"},
    "ToDo": {"on_update": "alantech_erp.sales.activity.todo_on_update"},
    # Campaign: owner / company defaults, child campaign checks, Actual Cost, Income, ROI (CRM C36)
    "Campaign": {
        "validate": "alantech_erp.sales.campaign.campaign_validate",
    },
    # Sales commission (alantech_erp/sales/commission.py): Commission Ledger Entries per Sales Team
    "Sales Invoice": {
        "validate": [
            "alantech_erp.sales.commission.fill_sales_team",
            # Campaign from the Sales Order / Customer (CRM C24)
            "alantech_erp.sales.campaign.sales_invoice_validate",
        ],
        "on_submit": "alantech_erp.sales.commission.on_sales_invoice_submit",
        "on_cancel": "alantech_erp.sales.commission.on_cancel",
    },
    "Payment Entry": {
        "on_submit": "alantech_erp.sales.commission.on_payment_entry_submit",
        "on_cancel": "alantech_erp.sales.commission.on_cancel",
    },
}

 

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "alantech_erp.alantech.doctype.document.document.send_expiry_alerts",
        "alantech_erp.alantech.doctype.session_log.builder.build_yesterday_logs",  # "Daily Scheduler"
        "alantech_erp.alantech.doctype.employee_asset_handover.exit_alerts.send_daily_reminders",
        # sales follow-ups due today / overdue, one notification per owner (CRM C10)
        "alantech_erp.sales.activity.send_follow_up_reminders",
    ],
    "monthly": [
        "alantech_erp.setup.shifts.ensure_holiday_lists",
        "alantech_erp.setup.shifts.sync_employee_holiday_lists",
    ],
}

# Testing
# -------

# before_tests = "alantech_erp.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"erpnext.setup.doctype.employee.employee.create_user": "alantech_erp.setup.employee_user.create_user",
	# bell list never cached by the browser: another user's list was shown after a re-login
	# (setup/notifications.py, ClickUp 14yr2e57crv)
	"frappe.desk.doctype.notification_log.notification_log.get_notification_logs": "alantech_erp.setup.notifications.get_notification_logs",
	# blank Employee template with Series pre-filled HR-EMP- (setup/employee_import.py, ClickUp 14yr2e57mja)
	"frappe.core.doctype.data_import.data_import.download_template": "alantech_erp.setup.employee_import.download_template",
	# Employee form "Create Assignments": no Salary Structure permission error for employees
	# (setup/employee_assignments.py)
	"hrms.overrides.employee_master.get_assignable_masters": "alantech_erp.setup.employee_assignments.get_assignable_masters",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "alantech_erp.task.get_dashboard_data"
# }
# calls, meetings, tasks and notes on the Lead / Customer / Deal timeline (CRM C10)
additional_timeline_content = {
	doctype: ["alantech_erp.sales.activity.timeline_content"] for doctype in ("Lead", "Customer", "Opportunity")
}
override_doctype_dashboards = {
	"Customer": "alantech_erp.sales.dashboards.customer",
	"Lead": "alantech_erp.sales.dashboards.lead",
	"Opportunity": "alantech_erp.sales.dashboards.opportunity",
	# child campaigns on the Campaign's Connections (CRM C36)
	"Campaign": "alantech_erp.sales.dashboards.campaign",
	"Employee": "alantech_erp.alantech.dashboards.employee",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["alantech_erp.utils.before_request"]
# after_request = ["alantech_erp.utils.after_request"]

# Job Events
# ----------
# before_job = ["alantech_erp.utils.before_job"]
# after_job = ["alantech_erp.utils.after_job"]


# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"alantech_erp.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# Login page branding ("Login to AlanTech" + logo)
after_install = [
    "alantech_erp.install.apply_branding"
    ]
after_migrate = [
    "alantech_erp.install.apply_branding",
    "alantech_erp.setup.access.extend_role_profiles",
    "alantech_erp.org_structure.setup_if_ready",
    "alantech_erp.setup.designations.execute",
    "alantech_erp.setup.access.execute",
    "alantech_erp.setup.employee_fields.execute",
    # Bank Branch / PF-Gratuity date / Probation fields; Part 1 fields ticked in the import template
    "alantech_erp.setup.employee_payroll_fields.execute",
    # Nationality custom field, ticked in the import template
    "alantech_erp.setup.employee_nationality.execute",
    "alantech_erp.setup.employee_validation.seed_employee_number_counter",
    "alantech_erp.setup.session_log_fields.execute",
    # Shift Type Work Mode / Early Check-in / Late Checkout / OT Rounding (before shifts.execute)
    "alantech_erp.setup.shift_ot_fields.execute",
    "alantech_erp.setup.shifts.execute",
    "alantech_erp.setup.leave_fields.execute",
    "alantech_erp.setup.sales_flow.execute",
    "alantech_erp.org_structure.fill_missing_reports_to",
    "alantech_erp.setup.approvers.execute",
    "alantech_erp.setup.leave_workflow.execute",
    "alantech_erp.setup.attendance_request.execute",
    # HR User prepares Payroll Entries; payroll payable account of type Payable
    "alantech_erp.setup.payroll.execute",
    "alantech_erp.setup.asset_handover.execute",
    # Employee / Employee Uniform Issue on the Stock Entry made by a uniform issue
    "alantech_erp.setup.uniform_issue.execute",
    # Quotation approval workflow (Sales Manager, Level 2 above the Selling Settings limit)
    "alantech_erp.setup.sales_flow.execute",
    # Sales Person for every active employee in the Sales department
    "alantech_erp.sales.sales_person.execute",
    # Sales forecast + commission: Deal Forecast Category / Sales Person, Sales Stage defaults
    "alantech_erp.setup.sales_performance.execute",
    # Campaigns (CRM C24, C36): Campaign owner / budget / costs / results, Customer campaign
    "alantech_erp.setup.campaigns.execute",
    # Employee Loan Rules: Lending Settings > Require Loan Rule (LR-02)
    "alantech_erp.setup.loan_rule_settings.execute",
    # Employee Loan Rules: Loan Eligibility section on Loan Application (LR-03)
    "alantech_erp.setup.loan_application_fields.execute",
    # Employee Loan Rules: HR roles on Loan Application / Loan Product / Loan (LR-09)
    "alantech_erp.setup.loan_permissions.execute",
    # HR Manager / HR User may open the Import dialog (Data Import rights, Employee import)
    "alantech_erp.setup.data_import_permissions.execute",
    # HR Settings > Default Notice Period (Days); Employee > Notice Period tab (ClickUp 14yr2e57r71)
    "alantech_erp.alantech.doctype.employee_notice_period.employee_notice_period.execute",
    # Loan Management flow (HR-F05-x): existing HR Managers get Loan Manager
    "alantech_erp.setup.loan_roles.execute",
    # Loan Management flow (HR-F05-x): employee loan ledgers, Loan Product accounts, Company settings
    "alantech_erp.setup.loan_accounts.execute",
    # demo / UAT sites only (site_config "alantech_demo_data": 1): keep last
    "alantech_erp.demo.data.after_migrate",
]

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
	"Salary Structure Assignment": "alantech_erp.setup.salary_access.salary_structure_assignment_query_conditions",
	"Salary Slip": "alantech_erp.setup.salary_access.salary_slip_query_conditions",
	"Lead": f"{_SALES_HIERARCHY}.lead_query",
	"Customer": f"{_SALES_HIERARCHY}.customer_query",
	"Opportunity": f"{_SALES_HIERARCHY}.opportunity_query",
	"Estimation": f"{_SALES_HIERARCHY}.estimation_query",
	"Technical Offer": f"{_SALES_HIERARCHY}.technical_offer_query",
	"Quotation": f"{_SALES_HIERARCHY}.quotation_query",
	"Sales Order": f"{_SALES_HIERARCHY}.sales_order_query",
}
has_permission = {
	"Document": "alantech_erp.alantech.doctype.document.document.has_permission",
	"Session Log": "alantech_erp.alantech.doctype.session_log.session_log.has_permission",
	"Holiday List": "alantech_erp.setup.shifts.holiday_list_has_permission",
	"Company Policy": "alantech_erp.alantech.doctype.company_policy.company_policy.has_permission",
	"Salary Structure Assignment": "alantech_erp.setup.salary_access.has_permission",
	"Salary Slip": "alantech_erp.setup.salary_access.has_permission",
	**{
		doctype: f"{_SALES_HIERARCHY}.has_permission"
		for doctype in ("Lead", "Customer", "Opportunity", "Estimation", "Technical Offer", "Quotation", "Sales Order")
	},
}
# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

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
    "Employee": {
        "before_insert": [
            # blank Employee Number (form or Data Import) -> next E### number
            "alantech_erp.setup.employee_validation.set_employee_number",
            "alantech_erp.setup.employee_user.employee_before_insert",
        ],
        "after_insert": "alantech_erp.setup.employee_user.employee_after_insert",
        "validate": [
            "alantech_erp.org_structure.apply_designation_defaults",
            "alantech_erp.setup.employee_validation.validate_unique_employee",
            "alantech_erp.setup.employee_validation.validate_unique_email",
            "alantech_erp.setup.employee_validation.validate_mobile_number",
            "alantech_erp.setup.access.employee_validate",
            # after apply_designation_defaults, which may fill Reports To
            "alantech_erp.setup.approvers.employee_validate",
            "alantech_erp.setup.shifts.employee_holiday_list",
            # last: Department / Reports To may be filled from the designation above
            "alantech_erp.setup.employee_validation.validate_required_on_create",
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
        ],
        "on_trash": "alantech_erp.sales.sales_person.employee_on_trash",
    },
    "Employee Separation": {
        "after_insert": "alantech_erp.alantech.doctype.employee_asset_handover.exit_alerts.employee_separation_after_insert",
    },
    "HR Settings": {
        "on_update": "alantech_erp.setup.employee_fields.show_employee_number_in_list",
    },
    "Salary Slip": {
        "validate": "alantech_erp.overtime_utils.add_overtime_components",
    },
    "Holiday List Assignment": {
        "validate": "alantech_erp.setup.shifts.set_assignment_status",
        "before_cancel": "alantech_erp.setup.shifts.set_assignment_status",
        "on_submit": "alantech_erp.setup.shifts.sync_employee_holiday_lists",
        "on_cancel": "alantech_erp.setup.shifts.sync_employee_holiday_lists",
    },
    "Employee Checkin": {
        "after_insert": "alantech_erp.alantech.doctype.session_log.builder.on_checkin",  # "On Check-out"
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
        "validate": "alantech_erp.sales.deal.validate_opportunity",
    },
    # Prospect flow not used (alantech_erp/sales/prospect.py)
    "Prospect": {
        "before_insert": "alantech_erp.sales.prospect.before_insert",
    },
    # Sales flow: Lead -> Customer -> Estimation -> Quotation (manager + client approval) -> Sales Order
    "Quotation": {
        "validate": "alantech_erp.sales.quotation.validate",
        "before_submit": "alantech_erp.sales.quotation.before_submit",
        "before_update_after_submit": "alantech_erp.sales.quotation.before_update_after_submit",
        "on_update_after_submit": "alantech_erp.sales.quotation.on_update_after_submit",
        # tell the salesperson when the quotation is approved / rejected
        "on_change": "alantech_erp.sales.quotation.on_change",
    },
    "Sales Order": {
        "validate": "alantech_erp.sales.sales_order.validate",
        "before_submit": "alantech_erp.sales.sales_order.before_submit",
        "on_submit": "alantech_erp.sales.sales_order.on_submit",
        "on_cancel": "alantech_erp.sales.sales_order.on_cancel",
    },
}

 

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "alantech_erp.alantech.doctype.document.document.send_expiry_alerts",
        "alantech_erp.alantech.doctype.session_log.builder.build_yesterday_logs",  # "Daily Scheduler"
        "alantech_erp.alantech.doctype.employee_asset_handover.exit_alerts.send_daily_reminders",
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
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "alantech_erp.task.get_dashboard_data"
# }
override_doctype_dashboards = {
	"Customer": "alantech_erp.sales.dashboards.customer",
	"Lead": "alantech_erp.sales.dashboards.lead",
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
    "alantech_erp.setup.employee_validation.seed_employee_number_counter",
    "alantech_erp.setup.session_log_fields.execute",
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
    # Quotation approval workflow (Sales Manager, Level 2 above the Selling Settings limit)
    "alantech_erp.setup.sales_flow.execute",
    # Sales Person for every active employee in the Sales department
    "alantech_erp.sales.sales_person.execute",
    # demo / UAT sites only (site_config "alantech_demo_data": 1): keep last
    "alantech_erp.demo.data.after_migrate",
]

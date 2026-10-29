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
    # live cost sheet calculation of the Estimation form
    "Estimation": "public/js/estimation_pricing.js",
    # approver lookup without an employee yet (Frappe v16 link validation)
    "Shift Request": "public/js/shift_request.js",
    # view-only Holiday List for employees
    "Holiday List": "public/js/holiday_list.js",
}
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

permission_query_conditions = {
	"Document": "alantech_erp.alantech.doctype.document.document.get_permission_query_conditions",
	"Session Log": "alantech_erp.alantech.doctype.session_log.session_log.get_permission_query_conditions",
	"Holiday List": "alantech_erp.setup.shifts.holiday_list_query_conditions",
}
has_permission = {
	"Document": "alantech_erp.alantech.doctype.document.document.has_permission",
	"Session Log": "alantech_erp.alantech.doctype.session_log.session_log.has_permission",
	"Holiday List": "alantech_erp.setup.shifts.holiday_list_has_permission",
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
    {"dt": "Role", "filters": [["name", "in", ["Proposal Engineer", "Design Engineer"]]]},
    {"dt": "Designation"},
    {"dt": "Department", "filters": [["name", "!=", "All Departments"]]},
    {"dt": "Document Type Master"}
]

doc_events = {
    "Employee": {
        "before_insert": "alantech_erp.setup.employee_user.employee_before_insert",
        "after_insert": "alantech_erp.setup.employee_user.employee_after_insert",
        "validate": [
            "alantech_erp.org_structure.apply_designation_defaults",
            "alantech_erp.setup.employee_validation.validate_unique_employee",
            "alantech_erp.setup.access.employee_validate",
            # after apply_designation_defaults, which may fill Reports To
            "alantech_erp.setup.approvers.employee_validate",
            "alantech_erp.setup.shifts.employee_holiday_list",
        ],
        "on_update": [
            "alantech_erp.org_structure.sync_user_role_profile",
            "alantech_erp.setup.access.employee_on_update",
            "alantech_erp.setup.approvers.employee_on_update",
            "alantech_erp.org_structure.fill_vacant_post",
        ],
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
    # Sales flow: Deal -> Estimation -> Quotation (manager + client approval) -> Sales Order
    "Quotation": {
        "validate": "alantech_erp.sales.quotation.validate",
        "before_submit": "alantech_erp.sales.quotation.before_submit",
        "before_update_after_submit": "alantech_erp.sales.quotation.before_update_after_submit",
        "on_update_after_submit": "alantech_erp.sales.quotation.on_update_after_submit",
    },
    "Sales Order": {
        "validate": "alantech_erp.sales.sales_order.validate",
    },
}

 

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "alantech_erp.alantech.doctype.document.document.send_expiry_alerts",
        "alantech_erp.alantech.doctype.session_log.builder.build_yesterday_logs",  # "Daily Scheduler"
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
    "alantech_erp.setup.session_log_fields.execute",
    "alantech_erp.setup.shifts.execute",
    "alantech_erp.setup.leave_fields.execute",
    "alantech_erp.org_structure.fill_missing_reports_to",
    "alantech_erp.setup.approvers.execute",
    "alantech_erp.setup.leave_workflow.execute",
]

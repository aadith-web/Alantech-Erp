"""Campaign fields (CRM requirements C24, C36; logic in alantech_erp/sales/campaign.py).

Campaign: Status, Type, Campaign Owner, Company, Start / End Date, Parent Campaign (child
campaigns), Budget, Costs (Campaign Cost rows), Actual Cost, Income from Sales Orders, ROI %.
Customer: Campaign (from the Lead it was converted from), so the campaign reaches the Estimation
and the Quotation made for the customer.
Lead / Deal / Quotation / Sales Order / Sales Invoice: ERPNext's own Campaign field (utm_campaign);
its section opens by itself when a campaign is set.

Runs on every `bench migrate` (after_migrate in hooks.py); safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cstr

from alantech_erp.sales import campaign as c

_CURRENCY = f"Company:{c.COMPANY_FIELD}:default_currency"
_RESULT = {"read_only": 1, "no_copy": 1}

CUSTOM_FIELDS = {
	"Campaign": [
		{
			"fieldname": c.STATUS_FIELD,
			"label": "Status",
			"fieldtype": "Select",
			"options": "\n".join(c.STATUSES),
			"default": c.STATUSES[0],
			"insert_after": "naming_series",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"reqd": 1,
		},
		{
			"fieldname": "alt_campaign_type",
			"label": "Campaign Type",
			"fieldtype": "Select",
			"options": "\nExhibition / Trade Show\nSeminar / Event\nEmail\nSocial Media\nWebsite / SEO\n"
			"Advertisement\nReferral\nTelemarketing\nOther",
			"insert_after": c.STATUS_FIELD,
			"in_list_view": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": c.PARENT_FIELD,
			"label": "Parent Campaign",
			"fieldtype": "Link",
			"options": "Campaign",
			"insert_after": "alt_campaign_type",
			"in_standard_filter": 1,
			"search_index": 1,
			"description": "Set on a child campaign: its results also count in the parent's totals",
		},
		{
			"fieldname": "alt_campaign_column",
			"fieldtype": "Column Break",
			"insert_after": c.PARENT_FIELD,
		},
		{
			"fieldname": c.OWNER_FIELD,
			"label": "Campaign Owner",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "alt_campaign_column",
			"default": "__user",
			"reqd": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": c.COMPANY_FIELD,
			"label": "Company",
			"fieldtype": "Link",
			"options": "Company",
			"insert_after": c.OWNER_FIELD,
			"reqd": 1,
			"remember_last_selected_value": 1,
		},
		{
			"fieldname": "alt_start_date",
			"label": "Start Date",
			"fieldtype": "Date",
			"insert_after": c.COMPANY_FIELD,
		},
		{
			"fieldname": "alt_end_date",
			"label": "End Date",
			"fieldtype": "Date",
			"insert_after": "alt_start_date",
		},
		# budget and cost
		{
			"fieldname": "alt_cost_section",
			"label": "Budget & Cost",
			"fieldtype": "Section Break",
			"insert_after": "alt_end_date",
		},
		{
			"fieldname": c.BUDGET_FIELD,
			"label": "Budget",
			"fieldtype": "Currency",
			"options": _CURRENCY,
			"insert_after": "alt_cost_section",
			"non_negative": 1,
			"in_list_view": 1,
		},
		{
			"fieldname": "alt_cost_column",
			"fieldtype": "Column Break",
			"insert_after": c.BUDGET_FIELD,
		},
		{
			"fieldname": c.ACTUAL_COST_FIELD,
			"label": "Actual Cost",
			"fieldtype": "Currency",
			"options": _CURRENCY,
			"insert_after": "alt_cost_column",
			"description": "Total of the cost rows below",
			**_RESULT,
		},
		{
			"fieldname": "alt_costs_break",
			"fieldtype": "Section Break",
			"insert_after": c.ACTUAL_COST_FIELD,
		},
		{
			"fieldname": c.COSTS_FIELD,
			"label": "Costs",
			"fieldtype": "Table",
			"options": "Campaign Cost",
			"insert_after": "alt_costs_break",
			"no_copy": 1,
		},
		# results
		{
			"fieldname": "alt_results_section",
			"label": "Results",
			"fieldtype": "Section Break",
			"insert_after": c.COSTS_FIELD,
			"description": "This campaign's own Sales Orders; the dashboard above adds the child campaigns",
		},
		{
			"fieldname": c.INCOME_FIELD,
			"label": "Income (Sales Orders)",
			"fieldtype": "Currency",
			"options": _CURRENCY,
			"insert_after": "alt_results_section",
			"description": "Net total of the submitted Sales Orders of this campaign",
			**_RESULT,
		},
		{
			"fieldname": "alt_results_column",
			"fieldtype": "Column Break",
			"insert_after": c.INCOME_FIELD,
		},
		{
			"fieldname": c.ROI_FIELD,
			"label": "ROI %",
			"fieldtype": "Percent",
			"insert_after": "alt_results_column",
			"description": "(Income - Actual Cost) / Actual Cost",
			**_RESULT,
		},
	],
	"Customer": [
		{
			"fieldname": c.CUSTOMER_FIELD,
			"label": "Campaign",
			"fieldtype": "Link",
			"options": c.UTM_DOCTYPE,
			"insert_after": "lead_name",
			"in_standard_filter": 1,
			"search_index": 1,
			"description": "The campaign the customer came from (from the Lead); passed on to Estimations and Quotations",
		},
	],
}

# the Campaign section of these forms opens when a campaign is set
CAMPAIGN_SECTION_DOCTYPES = ("Lead", "Opportunity", "Quotation", "Sales Order", "Sales Invoice")


def execute():
	if not frappe.db.exists("DocType", "Campaign") or not frappe.db.exists("DocType", "Campaign Cost"):
		return  # ERPNext not installed / app doctypes not synced yet
	create_custom_fields(CUSTOM_FIELDS, update=True)
	_open_campaign_sections()
	frappe.clear_cache(doctype="Campaign")
	frappe.db.commit()


def _open_campaign_sections():
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for doctype in CAMPAIGN_SECTION_DOCTYPES:
		meta = frappe.get_meta(doctype)
		df = meta.get_field("utm_analytics_section")
		if not df or not meta.has_field(c.UTM_FIELD):
			continue
		value = f"eval:doc.{c.UTM_FIELD}"
		if cstr(df.get("collapsible_depends_on")) != value:
			make_property_setter(
				doctype,
				"utm_analytics_section",
				"collapsible_depends_on",
				value,
				"Code",
				validate_fields_for_doctype=False,
			)


# --------------------------------------------------------------------------- backfill (patch)
def backfill():
	"""Fill the campaign of existing records down the flow (empty values only), then refresh the
	Income / ROI of every campaign. Called once by patches/v16/campaign_carry_through.py."""
	execute()

	# Customer <- its Lead
	if frappe.db.has_column("Customer", c.CUSTOMER_FIELD):
		for row in frappe.get_all(
			"Customer",
			filters={c.CUSTOMER_FIELD: ["is", "not set"], "lead_name": ["is", "set"]},
			fields=["name", "lead_name"],
		):
			value = c.lead_campaign(row.lead_name)
			if value:
				frappe.db.set_value("Customer", row.name, c.CUSTOMER_FIELD, value, update_modified=False)

	# Estimation <- Deal / Customer
	if frappe.db.has_column("Estimation", c.UTM_FIELD):
		for row in frappe.get_all(
			"Estimation", filters={c.UTM_FIELD: ["is", "not set"]}, fields=["name", "opportunity", "customer"]
		):
			value = c._get("Opportunity", row.opportunity, c.UTM_FIELD) or c.customer_campaign(row.customer)
			if value:
				frappe.db.set_value("Estimation", row.name, c.UTM_FIELD, value, update_modified=False)

	# Quotation <- Estimation / Deal / Customer or Lead
	for row in frappe.get_all(
		"Quotation",
		filters={c.UTM_FIELD: ["is", "not set"]},
		fields=["name", "alt_estimation", "opportunity", "quotation_to", "party_name"],
	):
		value = (
			c._get("Estimation", row.alt_estimation, c.UTM_FIELD)
			or c._get("Opportunity", row.opportunity, c.UTM_FIELD)
			or c._party_campaign(row.quotation_to, row.party_name)
		)
		if value:
			frappe.db.set_value("Quotation", row.name, c.UTM_FIELD, value, update_modified=False)

	# Deal <- Quotation
	for row in frappe.get_all(
		"Opportunity", filters={c.UTM_FIELD: ["is", "not set"], "alt_quotation": ["is", "set"]}, fields=["name", "alt_quotation"]
	):
		value = c._get("Quotation", row.alt_quotation, c.UTM_FIELD)
		if value:
			frappe.db.set_value("Opportunity", row.name, c.UTM_FIELD, value, update_modified=False)

	# Sales Order <- Quotation / Customer
	for row in frappe.get_all("Sales Order", filters={c.UTM_FIELD: ["is", "not set"]}, fields=["name", "customer"]):
		quotation = frappe.db.get_value(
			"Sales Order Item", {"parent": row.name, "prevdoc_docname": ["is", "set"]}, "prevdoc_docname"
		)
		value = c._get("Quotation", quotation, c.UTM_FIELD) or c.customer_campaign(row.customer)
		if value:
			frappe.db.set_value("Sales Order", row.name, c.UTM_FIELD, value, update_modified=False)

	for name in frappe.get_all("Campaign", pluck="name"):
		c.refresh_results(name)
	frappe.db.commit()

"""Sales forecast and commission setup (sales/forecast.py, sales/commission.py).

* Opportunity (Deal): Forecast Category and Sales Person.
* Sales Stage: the Forecast Category and Probability a Deal gets on reaching it, seeded for the
  Alantech stages (sales/__init__.py) without touching values already changed by hand.
* Existing Deals get their Sales Person (from the Deal owner) and category (from stage / status).
* Sales Performance Settings defaults.

Runs on every `bench migrate` (after_migrate in hooks.py); safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from alantech_erp.sales import (
	STAGE_ACCEPTED,
	STAGE_APPROVAL,
	STAGE_APPROVED,
	STAGE_DRAFT,
	STAGE_LOST,
	STAGE_REVISION,
	STAGE_SENT,
)
from alantech_erp.sales.forecast import (
	BEST_CASE,
	CATEGORIES,
	CATEGORY_FIELD,
	COMMIT,
	OMITTED,
	PIPELINE,
	SALES_PERSON_FIELD,
	SETTINGS,
	STAGE_PROBABILITY_FIELD,
	category_for_status,
)

CUSTOM_FIELDS = {
	"Opportunity": [
		{
			"fieldname": CATEGORY_FIELD,
			"label": "Forecast Category",
			"fieldtype": "Select",
			# leading blank: a new Deal starts empty and the Sales Stage decides (validate)
			"options": "\n" + "\n".join(CATEGORIES),
			"default": "",
			"insert_after": "probability",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"no_copy": 1,
			"description": "Set from the Sales Stage when it moves; change it to override (Commit = will close this period)",
		},
		{
			"fieldname": SALES_PERSON_FIELD,
			"label": "Sales Person",
			"fieldtype": "Link",
			"options": "Sales Person",
			"insert_after": "opportunity_owner",
			"in_standard_filter": 1,
			"search_index": 1,
			"read_only": 1,
			"description": "From the Deal owner's employee; the forecast rolls up the Sales Person tree from here",
		},
	],
	"Sales Stage": [
		{
			"fieldname": CATEGORY_FIELD,
			"label": "Forecast Category",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(CATEGORIES),
			"insert_after": "stage_name",
			"in_list_view": 1,
		},
		{
			"fieldname": STAGE_PROBABILITY_FIELD,
			"label": "Default Probability (%)",
			"fieldtype": "Percent",
			"insert_after": CATEGORY_FIELD,
			"in_list_view": 1,
			"description": "A Deal reaching this stage gets this probability",
		},
	],
}

# Alantech stages: (forecast category, probability %)
STAGE_DEFAULTS = {
	STAGE_DRAFT: (PIPELINE, 10),
	STAGE_REVISION: (PIPELINE, 30),
	STAGE_APPROVAL: (PIPELINE, 30),
	STAGE_APPROVED: (BEST_CASE, 50),
	STAGE_SENT: (BEST_CASE, 60),
	STAGE_ACCEPTED: (COMMIT, 90),
	STAGE_LOST: (OMITTED, 0),
}


def execute():
	if not frappe.db.exists("DocType", "Opportunity"):
		return  # ERPNext not installed
	create_custom_fields(CUSTOM_FIELDS, update=True)
	_seed_stages()
	_backfill_deals()
	_settings_defaults()
	frappe.db.commit()


def _seed_stages():
	for stage, (category, probability) in STAGE_DEFAULTS.items():
		if not frappe.db.exists("Sales Stage", stage):
			continue
		current = frappe.db.get_value(
			"Sales Stage", stage, [CATEGORY_FIELD, STAGE_PROBABILITY_FIELD], as_dict=True
		)
		if not current.get(CATEGORY_FIELD):  # never overwrite a category set by hand
			frappe.db.set_value(
				"Sales Stage",
				stage,
				{CATEGORY_FIELD: category, STAGE_PROBABILITY_FIELD: probability},
				update_modified=False,
			)


def _backfill_deals():
	from alantech_erp.sales.hierarchy import sales_person_of_user

	deals = frappe.get_all(
		"Opportunity",
		or_filters={SALES_PERSON_FIELD: ["is", "not set"], CATEGORY_FIELD: ["is", "not set"]},
		fields=[
			"name",
			"opportunity_owner",
			"owner",
			"sales_stage",
			"status",
			SALES_PERSON_FIELD,
			CATEGORY_FIELD,
		],
	)
	categories = dict(frappe.get_all("Sales Stage", fields=["name", CATEGORY_FIELD], as_list=True))
	for deal in deals:
		values = {}
		if not deal.get(SALES_PERSON_FIELD):
			person = sales_person_of_user(deal.opportunity_owner or deal.owner)
			if person:
				values[SALES_PERSON_FIELD] = person.name
		if not deal.get(CATEGORY_FIELD):
			values[CATEGORY_FIELD] = (
				category_for_status(deal.status) or categories.get(deal.sales_stage) or PIPELINE
			)
		if values:
			frappe.db.set_value("Opportunity", deal.name, values, update_modified=False)


def _settings_defaults():
	if not frappe.db.exists("DocType", SETTINGS):
		return
	doc = frappe.get_single(SETTINGS)
	if doc.won_source:
		return  # already set up
	doc.won_source = "Sales Order"
	doc.period_type = "Month"
	doc.enable_commission = 1
	doc.default_basis = "Sales Invoice"
	doc.payout_method = "Journal Entry"
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.save()

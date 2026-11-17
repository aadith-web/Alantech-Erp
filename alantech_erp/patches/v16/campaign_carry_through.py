"""Campaigns (CRM C24, C36): create the Campaign / Customer campaign fields and fill the campaign
of existing Customers, Estimations, Quotations, Deals and Sales Orders down the sales flow (empty
values only), then compute each campaign's Income and ROI."""


def execute():
	from alantech_erp.setup.campaigns import backfill

	backfill()

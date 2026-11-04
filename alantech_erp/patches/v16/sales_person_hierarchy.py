"""Rebuild the Sales Person tree on the sales line: Sales Director -> Sales Managers -> Sales Engineers.

Proposal Engineers and the Sales Co-ordinator report to Management, so their Sales Persons are
disabled (kept for old orders and targets). See alantech_erp/sales/sales_person.py.
"""

from alantech_erp.sales.sales_person import rebuild_tree


def execute():
	rebuild_tree()

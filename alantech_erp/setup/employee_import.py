"""Employee import template: Series pre-filled with HR-EMP-.

ClickUp: https://app.clickup.com/t/14yr2e57mja

- Download Template (blank template, Employee, Series column chosen): the Series column is filled
  with the default series (HR-EMP-) for PREFILLED_ROWS rows, so the user only fills the rest.
  Hooked as override_whitelisted_methods of Frappe's data_import.download_template.
- Import: rows in which Series (with the default value) is the only filled cell are pre-filled
  rows the user did not use; they are dropped before the import instead of failing as employees
  without a name. Hooked as override_doctype_class of Data Import.
- A blank Series cell or no Series column still works: Employee.autoname uses HR-EMP-.
Employee Number is ticked in the template too (setup/employee_fields.py) and gets the next E###
when left blank (employee_validation.set_employee_number).
"""

from typing import Any

import frappe
from frappe.core.doctype.data_import.data_import import DataImport
from frappe.core.doctype.data_import.data_import import download_template as frappe_download_template
from frappe.core.doctype.data_import.exporter import Exporter
from frappe.core.doctype.data_import.value_mapping import INVALID_VALUES
from frappe.model.naming import get_default_naming_series
from frappe.model.utils.user_settings import get_user_settings

DOCTYPE = "Employee"
SERIES_FIELD = "naming_series"
PREFILLED_ROWS = 100


@frappe.whitelist()
def download_template(
	doctype: str,
	export_fields: str | dict[str, list[str]] | None = None,
	export_records: str | None = None,
	export_filters: str | dict[str, Any] | list[list[Any]] | None = None,
	file_type: str = "CSV",
):
	"""Frappe's download_template; the blank Employee template gets Series pre-filled."""
	fields = frappe.parse_json(export_fields) or {}
	if doctype != DOCTYPE or export_records != "blank_template" or SERIES_FIELD not in (fields.get(DOCTYPE) or []):
		return frappe_download_template(doctype, export_fields, export_records, export_filters, file_type)

	frappe.has_permission(doctype, "read", throw=True)
	series = get_default_naming_series(DOCTYPE)
	exporter = Exporter(doctype, export_fields=fields, export_data=False, file_type=file_type)
	columns = [
		i for i, df in enumerate(exporter.fields) if df.fieldname == SERIES_FIELD and not df.is_child_table_field
	]
	if series and columns:
		row = [""] * len(exporter.fields)
		row[columns[0]] = series
		exporter.data = [list(row) for _ in range(PREFILLED_ROWS)]
		exporter.add_data()
	exporter.build_response()


class AlantechDataImport(DataImport):
	def get_importer(self):
		importer = super().get_importer()
		if self.reference_doctype == DOCTYPE:
			drop_prefilled_rows(importer.import_file)
		return importer


def drop_prefilled_rows(import_file):
	"""Remove rows whose only filled cell is Series with the default value, then re-parse."""
	series = get_default_naming_series(DOCTYPE)
	header = getattr(import_file, "header", None)
	if not series or not header:
		return
	series_columns = [
		col.index
		for col in import_file.columns
		if col.df and col.df.fieldname == SERIES_FIELD and col.df.parent == DOCTYPE
	]
	if len(series_columns) != 1:
		return
	idx = series_columns[0]

	def is_prefilled(row):
		if idx >= len(row) or str(row[idx]).strip() != series:
			return False
		return all(v in INVALID_VALUES for i, v in enumerate(row) if i != idx)

	start = header.index + 1
	data_rows = import_file.raw_data[start:]
	kept = [row for row in data_rows if not is_prefilled(row)]
	if len(kept) == len(data_rows):
		return
	import_file.raw_data = import_file.raw_data[:start] + kept
	import_file.__dict__.pop("_tree_preview_cache", None)
	import_file.parse_data_from_template()

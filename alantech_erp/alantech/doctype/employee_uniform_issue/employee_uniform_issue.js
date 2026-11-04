// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

const SETTINGS_API = "alantech_erp.alantech.doctype.uniform_issue_settings.uniform_issue_settings.get_uniform_defaults";
const ITEM_API = "alantech_erp.alantech.doctype.employee_uniform_issue.employee_uniform_issue.get_item_details";

frappe.ui.form.on("Employee Uniform Issue", {
  setup(frm) {
    frm.set_query("employee", () => ({ filters: { status: "Active" } }));

    frm.set_query("source_warehouse", () => {
      const filters = { disabled: 0, is_group: 0 };
      if (frm.doc.company) filters.company = frm.doc.company;
      return { filters };
    });

    // Only uniform items: stock items from the Uniform Item Group in the settings (if one is set)
    frm.set_query("item_code", "items", () => {
      const filters = { disabled: 0, is_stock_item: 1 };
      if (frm._uniform_item_group) {
        filters.item_group = ["descendants of (inclusive)", frm._uniform_item_group];
      }
      return { filters };
    });
  },

  onload(frm) {
    if (frm.is_new() && !frm.doc.company) {
      frm.set_value("company", frappe.defaults.get_user_default("Company"));
    }
    load_defaults(frm);
  },

  company(frm) {
    if (frm.is_new()) load_defaults(frm, true);
  },

  source_warehouse(frm) {
    refresh_rates(frm);
  },
});

frappe.ui.form.on("Employee Uniform Issue Item", {
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code) return;
    frappe
      .call({ method: ITEM_API, args: { item_code: row.item_code, warehouse: frm.doc.source_warehouse } })
      .then(({ message }) => {
        frappe.model.set_value(cdt, cdn, {
          item_name: message.item_name,
          uom: message.uom,
          rate: message.rate,
        });
      });
  },

  qty(frm, cdt, cdn) {
    update_row(frm, cdt, cdn);
  },

  rate(frm, cdt, cdn) {
    update_row(frm, cdt, cdn);
  },

  items_remove(frm) {
    calculate_totals(frm);
  },
});

// Defaults come from Uniform Issue Settings; the settings also give the uniform item group for the item filter.
function load_defaults(frm, force) {
  frappe.call({ method: SETTINGS_API, args: { company: frm.doc.company } }).then(({ message }) => {
    frm._uniform_item_group = message.uniform_item_group;
    if (frm.is_new() && message.default_source_warehouse && (force || !frm.doc.source_warehouse)) {
      frm.set_value("source_warehouse", message.default_source_warehouse);
    }
  });
}

function update_row(frm, cdt, cdn) {
  const row = locals[cdt][cdn];
  frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
  calculate_totals(frm);
}

function calculate_totals(frm) {
  let total_qty = 0;
  let total_amount = 0;
  (frm.doc.items || []).forEach((row) => {
    total_qty += flt(row.qty);
    total_amount += flt(row.qty) * flt(row.rate);
  });
  frm.set_value({ total_qty, total_amount });
}

// A new warehouse can change the valuation rate of every row
function refresh_rates(frm) {
  const rows = (frm.doc.items || []).filter((row) => row.item_code);
  Promise.all(
    rows.map((row) =>
      frappe.call({ method: ITEM_API, args: { item_code: row.item_code, warehouse: frm.doc.source_warehouse } })
    )
  ).then((results) => {
    rows.forEach((row, i) => frappe.model.set_value(row.doctype, row.name, "rate", results[i].message.rate));
  });
}
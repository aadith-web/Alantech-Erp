// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

frappe.ui.form.on("Uniform Issue Settings", {
  setup(frm) {
    frm.set_query("default_source_warehouse", () => ({
      filters: { disabled: 0, is_group: 0, ...company_filter(frm) },
    }));
    frm.set_query("uniform_expense_account", () => ({
      filters: { disabled: 0, is_group: 0, root_type: "Expense", ...company_filter(frm) },
    }));
    frm.set_query("default_cost_center", () => ({
      filters: { disabled: 0, is_group: 0, ...company_filter(frm) },
    }));
  },

  refresh(frm) {
    set_company_context(frm);
  },

  default_source_warehouse(frm) {
    set_company_context(frm);
  },
  uniform_expense_account(frm) {
    set_company_context(frm);
  },
  default_cost_center(frm) {
    set_company_context(frm);
  },
});

// The settings have no company field: once one of warehouse / account / cost center is
// chosen, its company narrows the other two lists.
function set_company_context(frm) {
  const sources = [
    ["Warehouse", frm.doc.default_source_warehouse],
    ["Account", frm.doc.uniform_expense_account],
    ["Cost Center", frm.doc.default_cost_center],
  ].find(([, name]) => name);

  if (!sources) {
    frm._company_context = null;
    return;
  }
  frappe.db.get_value(sources[0], sources[1], "company").then(({ message }) => {
    frm._company_context = message && message.company;
  });
}

function company_filter(frm) {
  return frm._company_context ? { company: frm._company_context } : {};
}
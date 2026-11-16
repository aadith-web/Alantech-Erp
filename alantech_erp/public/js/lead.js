// Lead: a verified lead becomes a Customer (Company or Individual) before any estimation or quote.
// No Deal or Quotation straight from the Lead: the Deal is made from the Quotation (Create Deal).
// No Prospect flow either (alantech_erp/sales/prospect.py).
frappe.ui.form.on("Lead", {
  refresh(frm) {
    if (frm.is_new()) return;
    // ERPNext adds its Create / Action buttons after this handler runs
    setTimeout(() => {
      frm.remove_custom_button(__("Opportunity"), __("Create"));
      frm.remove_custom_button(__("Quotation"), __("Create"));
      frm.remove_custom_button(__("Prospect"), __("Create"));
      frm.remove_custom_button(__("Add to Prospect"), __("Action"));
    }, 0);
    // Calls, meetings, tasks, notes: Activity menu and panel from public/js/sales_activity.js (CRM C10)
  },
});

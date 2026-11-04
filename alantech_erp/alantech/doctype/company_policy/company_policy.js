frappe.ui.form.on("Company Policy", {
  setup(frm) {
    frm.set_query("category", () => ({ filters: { enabled: 1 } }));
  },
});
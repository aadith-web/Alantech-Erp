// Employee Grade: only enabled Sub Bands in the Sub Bands table (ClickUp 14yr2e586v1).
frappe.ui.form.on("Employee Grade", {
	setup(frm) {
		frm.set_query("sub_band", "alt_sub_bands", () => ({ filters: { enabled: 1 } }));
	},
});

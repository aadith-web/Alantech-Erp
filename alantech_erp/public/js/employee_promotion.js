// Employee Promotion: Grade, Sub Band and Amount (ClickUp 14yr2e58nc6, setup/promotion_grade.py).
// Sub Band lists only the enabled sub bands of the chosen Grade; picking one fills the Amount with
// its Gross Amount (editable). The server checks the same and uses the Amount as Revised CTC on submit.
frappe.ui.form.on("Employee Promotion", {
	setup(frm) {
		frm.set_query("alt_sub_band", () => ({
			filters: { name: ["in", (frm.__alt_grade_bands || []).map((r) => r.sub_band)] },
		}));
	},
	refresh(frm) {
		alt_load_grade_bands(frm);
	},
	alt_grade(frm) {
		frm.set_value({ alt_sub_band: "", alt_amount: 0 });
		alt_load_grade_bands(frm);
	},
	alt_sub_band(frm) {
		const row = (frm.__alt_grade_bands || []).find((r) => r.sub_band === frm.doc.alt_sub_band);
		if (row) frm.set_value("alt_amount", row.gross_amount);
	},
	alt_amount(frm) {
		if (flt(frm.doc.alt_amount) < 0) {
			frappe.show_alert({ message: __("Amount cannot be negative."), indicator: "red" });
			frm.set_value("alt_amount", 0);
		}
	},
});

function alt_load_grade_bands(frm) {
	frm.__alt_grade_bands = [];
	if (!frm.doc.alt_grade) return;
	frappe
		.xcall("alantech_erp.setup.salary_structure_popup.get_grade_details", { grade: frm.doc.alt_grade })
		.then((d) => {
			frm.__alt_grade_bands = (d && d.sub_bands) || [];
			frm.set_df_property(
				"alt_sub_band",
				"description",
				frm.__alt_grade_bands.length
					? __("Sub bands of {0}: {1}", [frm.doc.alt_grade, frm.__alt_grade_bands.map((r) => r.sub_band).join(", ")])
					: __("Grade {0} has no enabled sub bands. Add them on the Employee Grade.", [frm.doc.alt_grade])
			);
		});
}

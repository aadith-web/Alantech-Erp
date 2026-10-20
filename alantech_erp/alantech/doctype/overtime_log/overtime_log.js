frappe.ui.form.on("Overtime Log", {
	overtime_hours(frm) {
		frm.trigger("calculate_amount");
	},

	overtime_rate(frm) {
		frm.trigger("calculate_amount");
	},

	set_amount_manually(frm) {
		frm.trigger("calculate_amount");
	},

	calculate_amount(frm) {
		if (frm.doc.set_amount_manually) return;
		const amount = flt(frm.doc.overtime_hours) * flt(frm.doc.overtime_rate);
		frm.set_value("overtime_amount", flt(amount, precision("overtime_amount")));
	},
});
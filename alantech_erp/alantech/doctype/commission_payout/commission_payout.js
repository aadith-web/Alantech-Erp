// Commission Payout: Get Commission fills the period's unpaid commission per Sales Person; submit
// pays it through a Journal Entry or Additional Salary (see commission_payout.py).
frappe.ui.form.on("Commission Payout", {
	setup(frm) {
		frm.set_query("expense_account", () => ({
			filters: { company: frm.doc.company, is_group: 0, root_type: "Expense" },
		}));
		frm.set_query("payable_account", () => ({
			filters: { company: frm.doc.company, is_group: 0, root_type: "Liability" },
		}));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("salary_component", () => ({ filters: { type: "Earning" } }));
	},
	onload(frm) {
		if (frm.is_new() && !frm.doc.period_start) {
			// commission is usually paid for the month just closed
			frm.set_value("period_start", frappe.datetime.add_months(frappe.datetime.get_today(), -1));
		}
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Commission"), () =>
				frm.call({ doc: frm.doc, method: "get_commission", freeze: true }).then(() => {
					frm.refresh_fields();
					frm.dirty();
				})
			).addClass("btn-primary");
		}
		frm.add_custom_button(
			__("Commission Statement"),
			() =>
				frappe.set_route("query-report", "Commission Statement", {
					company: frm.doc.company,
					from_date: frm.doc.from_date,
					to_date: frm.doc.to_date,
					sales_person: frm.doc.sales_person,
				}),
			__("View")
		);
	},
});

frappe.ui.form.on("Commission Payout Detail", {
	adjustment(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "payable_amount", flt(row.commission_amount) + flt(row.adjustment));
		frm.set_value(
			"total_payable",
			(frm.doc.details || []).reduce((s, r) => s + flt(r.payable_amount), 0)
		);
	},
});

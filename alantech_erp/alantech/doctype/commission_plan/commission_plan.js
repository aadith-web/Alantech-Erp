// Commission Plan: Try It works the commission out for an amount (and target) with the saved plan.
frappe.ui.form.on("Commission Plan", {
	setup(frm) {
		frm.set_query("sales_person", "members", () => ({ filters: { enabled: 1 } }));
	},
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Try It"), () => {
			const achievement = frm.doc.slab_basis === "Target Achievement %" && frm.doc.calculation_method.startsWith("Tiered");
			const d = new frappe.ui.Dialog({
				title: __("Try Commission Plan"),
				fields: [
					{ fieldname: "amount", fieldtype: "Currency", label: __("Sales in the Period"), reqd: 1 },
					{ fieldname: "target", fieldtype: "Currency", label: __("Target for the Period"), reqd: achievement },
					{ fieldname: "result", fieldtype: "HTML" },
				],
				primary_action_label: __("Calculate"),
				primary_action(values) {
					frappe
						.call("alantech_erp.alantech.doctype.commission_plan.commission_plan.preview", {
							plan: frm.doc.name,
							amount: values.amount,
							target: values.target || 0,
						})
						.then((r) => {
							const m = r.message;
							d.fields_dict.result.$wrapper.html(`
								<div class="mt-3">
									<div>${__("Commission")}: <b>${format_currency(m.commission)}</b></div>
									<div class="text-muted small">${__("Effective rate")}: ${flt(m.rate, 2)}%
									${values.target ? ` · ${__("Achieved")}: ${flt(m.achievement, 1)}%` : ""}</div>
								</div>`);
						});
				},
			});
			d.show();
		});
		frm.add_custom_button(__("Commission Statement"), () =>
			frappe.set_route("query-report", "Commission Statement", { company: frm.doc.company })
		);
	},
});

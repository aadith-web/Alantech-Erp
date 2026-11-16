// Sales Forecast: Get Forecast fills the team's live numbers; the manager sets the Manager Forecast
// per row and submits to freeze it (see sales_forecast.py).
frappe.ui.form.on("Sales Forecast", {
	setup(frm) {
		frm.set_query("sales_person", () => ({ filters: { enabled: 1 } }));
	},
	onload(frm) {
		if (frm.is_new() && !frm.doc.period_start) {
			frm.set_value("period_start", frappe.datetime.get_today());
		}
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Forecast"), () => get_forecast(frm)).addClass("btn-primary");
		}
		frm.add_custom_button(
			__("Forecast Report"),
			() =>
				frappe.set_route("query-report", "Sales Forecast", {
					company: frm.doc.company,
					period_type: frm.doc.period_type,
					period_start: frm.doc.period_start,
					sales_person: frm.doc.sales_person,
				}),
			__("View")
		);
		indent_rows(frm);
	},
	sales_person: (frm) => frm.doc.docstatus === 0 && frm.doc.period_start && get_forecast(frm),
	period_type: (frm) => frm.doc.docstatus === 0 && frm.doc.period_start && get_forecast(frm),
	period_start: (frm) => frm.doc.docstatus === 0 && frm.doc.company && get_forecast(frm),
});

frappe.ui.form.on("Sales Forecast Detail", {
	manager_adjusted(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const gap = row.target ? flt(row.target) - flt(row.manager_adjusted) : 0;
		frappe.model.set_value(cdt, cdn, "gap", gap);
		const top = (frm.doc.details || []).filter((r) => !r.indent);
		frm.set_value(
			"total_manager_forecast",
			top.reduce((sum, r) => sum + flt(r.manager_adjusted), 0)
		);
	},
});

function get_forecast(frm) {
	if (!frm.doc.company || !frm.doc.period_start) return;
	return frm.call({ doc: frm.doc, method: "fill_details", freeze: true }).then(() => {
		frm.refresh_fields();
		indent_rows(frm);
		frm.dirty();
	});
}

// show the tree in the grid: Sales Person indented by its level, teams in bold
function indent_rows(frm) {
	setTimeout(() => {
		(frm.fields_dict.details?.grid?.grid_rows || []).forEach((grid_row) => {
			const doc = grid_row.doc;
			const $cell = $(grid_row.row).find('[data-fieldname="sales_person"] .static-area');
			$cell.css({ "padding-left": `${(doc.indent || 0) * 14}px`, "font-weight": doc.is_group ? 600 : 400 });
		});
	}, 300);
}

// Holiday List for users who can only read it (employees): the dates, nothing else. Hides the
// Add Weekly / Add Local Holidays tools, Clear Table, colour / country, and the Connections
// (Company, Service Level Agreement, Shift Type, Employee). In the Holidays table: no row
// checkboxes, no edit (pencil) column, no column settings, and clicking a row opens nothing.
// HR (write access) sees the full form.
// Loaded through doctype_js in hooks.py, after ERPNext's own Holiday List script.

const ALT_HOLIDAY_LIST_VIEW_FIELDS = [
	"holiday_list_name",
	"from_date",
	"to_date",
	"column_break_4",
	"total_holidays",
	"holidays_section",
	"holidays",
];

// every grid row (heading, filter, data) ends with the action column: settings / empty / pencil.
// The No. column is sticky at left: 31px (after the checkbox); without the checkbox it sits at 0.
frappe.dom.set_style(
	`.alt-grid-view-only .row-check,
	.alt-grid-view-only .data-row > .col:last-child { display: none !important; }
	.alt-grid-view-only .row-index { left: 0 !important; }`,
	"alt-grid-view-only"
);

frappe.ui.form.on("Holiday List", {
	refresh(frm) {
		const view_only = !frm.is_new() && !frm.perm[0]?.write;
		alt_holiday_grid_view_only(frm.fields_dict.holidays.grid, view_only);
		if (!view_only) return;

		for (const df of frm.meta.fields) {
			if (!ALT_HOLIDAY_LIST_VIEW_FIELDS.includes(df.fieldname)) {
				frm.toggle_display(df.fieldname, false);
			}
		}
		frm.dashboard.links_area?.hide();
	},
});

function alt_holiday_grid_view_only(grid, view_only) {
	grid.wrapper.toggleClass("alt-grid-view-only", view_only);
	if (grid.alt_row_clicks_blocked) return;
	grid.alt_row_clicks_blocked = true;
	// capture phase: stops the click before the row's handler opens the row form
	grid.wrapper[0].addEventListener(
		"click",
		(e) => {
			if (grid.wrapper.hasClass("alt-grid-view-only") && e.target.closest(".grid-body .data-row")) {
				e.stopPropagation();
			}
		},
		true
	);
}

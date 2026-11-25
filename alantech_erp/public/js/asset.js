// Asset: Opening Stock for an Existing Asset (ClickUp 14yr2e58hv1, setup/asset_opening_stock.py).
// The field itself shows only for Asset Type = Existing Asset (depends_on); here: progress of the
// background creation of the other units on a submitted asset.
const ALT_OPENING = "alantech_erp.setup.asset_opening_stock";

frappe.ui.form.on("Asset", {
	refresh(frm) {
		alt_opening_stock_status(frm);
	},
	asset_type(frm) {
		if (frm.doc.asset_type !== "Existing Asset" && frm.doc.alt_opening_stock) frm.set_value("alt_opening_stock", 0);
	},
	alt_opening_stock(frm) {
		if (cint(frm.doc.alt_opening_stock) > 1 && cint(frm.doc.asset_quantity) !== 1) frm.set_value("asset_quantity", 1);
	},
});

function alt_opening_stock_status(frm) {
	if (frm.doc.docstatus !== 1 || frm.doc.asset_type !== "Existing Asset" || cint(frm.doc.alt_opening_stock) < 2) return;
	frappe.xcall(`${ALT_OPENING}.get_opening_stock_status`, { asset: frm.doc.name }).then((s) => {
		if (!s || !s.total) return;
		const done = s.created >= s.total;
		frm.dashboard.set_headline_alert(
			done
				? __("Opening Stock: all {0} assets created.", [s.total])
				: __("Opening Stock: {0} of {1} assets created; the rest are being created in the background.", [s.created, s.total]),
			done ? "green" : "orange"
		);
		frm.add_custom_button(__("Opening Stock Assets"), () =>
			frappe.set_route("List", "Asset", { alt_opening_stock_of: frm.doc.name })
		, __("View"));
		if (!done && frm.perm[0] && frm.perm[0].submit) {
			frm.add_custom_button(__("Create Missing Assets"), () =>
				frappe.xcall(`${ALT_OPENING}.create_missing_assets`, { asset: frm.doc.name }).then(() =>
					frappe.show_alert({ message: __("Creating the remaining assets in the background"), indicator: "blue" })
				)
			);
		}
	});
}

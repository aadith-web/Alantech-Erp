// Asset: Create As Grouped Asset / Single Asset (ClickUp 14yr2e58hv1, setup/asset_creation_mode.py).
// On a submitted Single Asset: progress of the background creation of the other assets.
// Actions > Split Asset hidden when the Asset Quantity is 1.
const ALT_ASSET_MODE = "alantech_erp.setup.asset_creation_mode";

frappe.ui.form.on("Asset", {
	refresh(frm) {
		// nothing to split off an asset of quantity 1 (ERPNext would only refuse it in the dialog)
		if (frm.doc.docstatus === 1 && cint(frm.doc.asset_quantity) <= 1) {
			frm.remove_custom_button(__("Split Asset"), __("Actions"));
		}
		alt_single_asset_status(frm);
	},
});

function alt_single_asset_status(frm) {
	if (frm.doc.docstatus !== 1 || frm.doc.alt_asset_creation !== "Single Asset") return;
	frappe.xcall(`${ALT_ASSET_MODE}.get_single_asset_status`, { asset: frm.doc.name }).then((s) => {
		if (!s || s.total < 2) return;
		const done = s.remaining <= 0;
		frm.dashboard.set_headline_alert(
			done
				? __("Single Asset: all {0} assets created (quantity 1 each).", [s.total])
				: __("Single Asset: {0} of {1} assets created; the rest are being created in the background.", [s.created, s.total]),
			done ? "green" : "orange"
		);
		frm.add_custom_button(
			__("Single Assets"),
			() => frappe.set_route("List", "Asset", { split_from: frm.doc.name }),
			__("View")
		);
		if (!done && frm.perm[0] && frm.perm[0].submit) {
			frm.add_custom_button(__("Create Remaining Assets"), () =>
				frappe.xcall(`${ALT_ASSET_MODE}.create_remaining_assets`, { asset: frm.doc.name }).then(() =>
					frappe.show_alert({ message: __("Creating the remaining assets in the background"), indicator: "blue" })
				)
			);
		}
	});
}

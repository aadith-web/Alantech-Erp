// Customer quick entry (ERPNext / India Compliance): Tax Type Local -> GSTIN and the primary
// address are mandatory, so the GST address is created with the customer
// (alantech_erp/sales/customer.py). Overseas -> GST Category Overseas, no GSTIN.
//
// India Compliance and ERPNext each set frappe.ui.form.CustomerQuickEntryForm, in app order; the
// property below wraps whichever class is set last, so this file can load before or after them.
(() => {
	frappe.provide("frappe.ui.form");

	const LOCAL_ONLY = "eval:doc.alt_tax_type=='Local'";
	// India Compliance names first, then ERPNext's own quick entry fields
	const GSTIN_FIELDS = ["_gstin", "gstin"];
	const ADDRESS_FIELDS = ["address_line1", "city", "state", "_pincode", "pincode", "country", "country_address"];

	function wrap(Base) {
		if (!Base || Base.__alt_tax_type) return Base;

		class AltCustomerQuickEntryForm extends Base {
			render_dialog() {
				super.render_dialog();
				const dialog = this.dialog;
				if (!dialog || !dialog.fields_dict.alt_tax_type) return;

				for (const fieldname of [...GSTIN_FIELDS, ...ADDRESS_FIELDS]) {
					const field = dialog.fields_dict[fieldname];
					if (field) field.df.mandatory_depends_on = LOCAL_ONLY;
				}
				for (const fieldname of GSTIN_FIELDS) {
					const field = dialog.fields_dict[fieldname];
					if (field) field.df.depends_on = "eval:doc.alt_tax_type!='Overseas'";
				}

				const tax_type = dialog.fields_dict.alt_tax_type;
				const previous = tax_type.df.onchange;
				tax_type.df.onchange = function () {
					if (previous) previous.apply(this, arguments);
					const value = dialog.get_value("alt_tax_type");
					if (dialog.fields_dict.gst_category) {
						if (value === "Overseas") dialog.set_value("gst_category", "Overseas");
						else if (value === "Local" && ["", "Overseas", "Unregistered"].includes(dialog.get_value("gst_category") || ""))
							dialog.set_value("gst_category", "Registered Regular");
					}
					if (value === "Overseas") {
						for (const fieldname of GSTIN_FIELDS) {
							if (dialog.fields_dict[fieldname]) dialog.set_value(fieldname, "");
						}
					}
					dialog.refresh_dependency();
				};
				dialog.refresh_dependency();
			}
		}
		AltCustomerQuickEntryForm.__alt_tax_type = true;
		return AltCustomerQuickEntryForm;
	}

	let current = wrap(frappe.ui.form.CustomerQuickEntryForm);
	Object.defineProperty(frappe.ui.form, "CustomerQuickEntryForm", {
		configurable: true,
		enumerable: true,
		get: () => current,
		set: (value) => {
			current = wrap(value);
		},
	});
})();

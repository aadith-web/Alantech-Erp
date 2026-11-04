// Customer quick entry (ERPNext / India Compliance): Tax Type Local -> GSTIN and the primary
// address are mandatory, so the GST address is created with the customer
// (alantech_erp/sales/customer.py). Overseas -> GST Category Overseas, no GSTIN.
// CRM-F04: Email and Mobile Number mandatory (mobile with its country code, unique per customer,
// sales/customer_unique.py); GSTIN optional for an Individual.
//
// India Compliance and ERPNext each set frappe.ui.form.CustomerQuickEntryForm, in app order; the
// property below wraps whichever class is set last, so this file can load before or after them.
(() => {
	frappe.provide("frappe.ui.form");

	const LOCAL_ONLY = "eval:doc.alt_tax_type=='Local'";
	const GSTIN_NEEDED = "eval:doc.alt_tax_type=='Local' && doc.customer_type!='Individual'";
	// ERPNext aliases (email_address / mobile_number), India Compliance and plain names
	const EMAIL_FIELDS = ["email_address", "_email_id", "email_id"];
	const MOBILE_FIELDS = ["mobile_number", "_mobile_no", "mobile_no"];
	// India Compliance names first, then ERPNext's own quick entry fields
	const GSTIN_FIELDS = ["_gstin", "gstin"];
	const ADDRESS_FIELDS = ["address_line1", "city", "state", "_pincode", "pincode", "country", "country_address"];

	function wrap(Base) {
		if (!Base || Base.__alt_tax_type) return Base;

		class AltCustomerQuickEntryForm extends Base {
			get_variant_fields() {
				const fields = super.get_variant_fields ? super.get_variant_fields() : [];
				for (const df of fields) {
					if (EMAIL_FIELDS.includes(df.fieldname)) df.reqd = 1;
					if (MOBILE_FIELDS.includes(df.fieldname)) {
						df.reqd = 1;
						// country code picker (+91-9847012345), as on Employee Mobile
						if (df.fieldtype === "Data") {
							df.fieldtype = "Phone";
							delete df.options;
						}
					}
				}
				return fields;
			}

			render_dialog() {
				super.render_dialog();
				const dialog = this.dialog;
				if (!dialog || !dialog.fields_dict.alt_tax_type) return;

				for (const fieldname of ADDRESS_FIELDS) {
					const field = dialog.fields_dict[fieldname];
					if (field) field.df.mandatory_depends_on = LOCAL_ONLY;
				}
				for (const fieldname of GSTIN_FIELDS) {
					const field = dialog.fields_dict[fieldname];
					if (field) field.df.mandatory_depends_on = GSTIN_NEEDED;
				}
				for (const fieldname of [...EMAIL_FIELDS, ...MOBILE_FIELDS]) {
					const field = dialog.fields_dict[fieldname];
					if (field) field.df.reqd = 1;
				}
				const customer_type = dialog.fields_dict.customer_type;
				if (customer_type) {
					const previous_type = customer_type.df.onchange;
					customer_type.df.onchange = function () {
						if (previous_type) previous_type.apply(this, arguments);
						dialog.refresh_dependency();
					};
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

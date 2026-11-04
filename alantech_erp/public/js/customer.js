// Customer (Company = Zoho Account, Individual = Zoho Contact): Estimation and Quotation are made
// for the customer; the Deal comes from the Quotation.
// Tax Type (alantech_erp/sales/customer.py): Local -> GSTIN mandatory (optional for an Individual)
// and an address with that GSTIN; Overseas -> GST Category Overseas, no GSTIN, Default Currency.
// CRM-F04: Mobile No and Email ID mandatory and unique (sales/customer_unique.py); Company /
// Partnership: Territory and Industry mandatory; Customer Type / Tax Type / GSTIN locked after
// the first submitted transaction (except for a Sales Manager).

const ALT_LOCAL = "Local";
const ALT_OVERSEAS = "Overseas";
const ALT_INDIVIDUAL = "Individual";
const ALT_LOCKED_FIELDS = ["customer_type", "alt_tax_type", "gstin"];

frappe.ui.form.on("Customer", {
	refresh(frm) {
		alt_apply_tax_type(frm);
		alt_apply_customer_type(frm);
		alt_apply_lock(frm);
		if (frm.is_new() || frm.doc.disabled) return;
		if (frappe.model.can_create("Estimation")) {
			frm.add_custom_button(
				__("Estimation"),
				() =>
					frappe.new_doc("Estimation", {
						customer: frm.doc.name,
						customer_name: frm.doc.customer_name,
						sales_user: frm.doc.account_manager || frm.doc.owner,
					}),
				__("Create")
			);
		}
		if (frm.doc.alt_customer_stage === "Account") {
			frm.set_intro(__("Account: becomes a Customer with its first confirmed Sales Order."), "blue");
		}
		alt_show_address_prompt(frm);
	},

	customer_type(frm) {
		alt_apply_customer_type(frm);
		alt_apply_tax_type(frm);
		if (frm.doc.customer_type === ALT_INDIVIDUAL && frm.doc.alt_tax_type === ALT_LOCAL && !frm.doc.gstin && frm.fields_dict.gst_category) {
			frm.set_value("gst_category", "Unregistered");
		}
	},

	alt_tax_type(frm) {
		const tax_type = frm.doc.alt_tax_type;
		if (frm.fields_dict.gst_category) {
			if (tax_type === ALT_OVERSEAS) {
				frm.set_value("gst_category", "Overseas");
				if (frm.doc.gstin) frm.set_value("gstin", "");
			} else if (tax_type === ALT_LOCAL && frm.doc.customer_type === ALT_INDIVIDUAL && !frm.doc.gstin) {
				frm.set_value("gst_category", "Unregistered");
			} else if (tax_type === ALT_LOCAL && ["", "Overseas", "Unregistered"].includes(frm.doc.gst_category || "")) {
				frm.set_value("gst_category", "Registered Regular");
			}
		}
		alt_apply_tax_type(frm);
	},

	after_save(frm) {
		// a new Local customer without an address from the quick entry or its Lead: add it now
		const problem = frm.doc.__onload && frm.doc.__onload.alt_address_problem;
		if (frm.doc.alt_tax_type === ALT_LOCAL && problem && !frm.doc.disabled) {
			frappe.confirm(
				`${frappe.utils.escape_html(problem)}<br><br>${__("Add the address now?")}`,
				() => alt_new_address(frm)
			);
		}
	},
});

function alt_apply_tax_type(frm) {
	const local = frm.doc.alt_tax_type === ALT_LOCAL;
	if (frm.fields_dict.gstin) {
		frm.toggle_reqd("gstin", local && frm.doc.customer_type !== ALT_INDIVIDUAL);
		frm.set_df_property("gstin", "read_only", frm.doc.alt_tax_type === ALT_OVERSEAS ? 1 : 0);
	}
	if (frm.fields_dict.default_currency) {
		frm.toggle_reqd("default_currency", frm.doc.alt_tax_type === ALT_OVERSEAS);
	}
}

function alt_apply_customer_type(frm) {
	const company = frm.doc.customer_type !== ALT_INDIVIDUAL;
	for (const field of ["territory", "industry"]) {
		if (frm.fields_dict[field]) frm.toggle_reqd(field, company);
	}
	if (frm.is_new()) {
		for (const field of ["mobile_no", "email_id"]) {
			if (frm.fields_dict[field]) frm.toggle_reqd(field, true);
		}
	}
}

function alt_apply_lock(frm) {
	// Customer Type / Tax Type / GSTIN after the first submitted transaction (sales/customer.py)
	const locked_by = frm.doc.__onload && frm.doc.__onload.alt_locked_by;
	if (!locked_by || frm.is_new()) return;
	for (const field of ALT_LOCKED_FIELDS) {
		if (frm.fields_dict[field]) frm.set_df_property(field, "read_only", 1);
	}
	frm.set_df_property(
		"alt_tax_type",
		"description",
		__("Customer Type, Tax Type and GSTIN are fixed after the first submitted {0}. A Sales Manager can change them.", [__(locked_by)])
	);
}

function alt_show_address_prompt(frm) {
	const problem = frm.doc.__onload && frm.doc.__onload.alt_address_problem;
	if (frm.doc.alt_tax_type !== ALT_LOCAL || !problem) return;
	frm.set_intro(frappe.utils.escape_html(problem), "red");
	frm.add_custom_button(__("Add GST Address"), () => alt_new_address(frm)).addClass("btn-primary");
}

function alt_new_address(frm) {
	// links the new address to this customer (Address form / India Compliance quick entry)
	frappe.dynamic_link = { doc: frm.doc, fieldname: "name", doctype: "Customer" };
	frappe.new_doc("Address", {
		address_title: frm.doc.customer_name,
		address_type: "Billing",
		is_primary_address: 1,
		country: "India",
		gstin: frm.doc.gstin,
		gst_category: frm.doc.gst_category,
	});
}

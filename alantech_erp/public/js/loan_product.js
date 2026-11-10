// Loan Product: show the mandatory asterisk on the collection offset sequences that
// Lending's server validation requires (LoanProduct.validate_demand_offset_sequences).
// Standard and Sub Standard Asset are mandatory unless the Company already sets them;
// when it does, the field stays optional and its description names the Company's value.

const ALT_COMPANY_OFFSET_FIELDS = [
	"collection_offset_sequence_for_standard_asset",
	"collection_offset_sequence_for_sub_standard_asset",
];

frappe.ui.form.on("Loan Product", {
	refresh(frm) {
		alt_toggle_offset_sequence_reqd(frm);
	},
	company(frm) {
		alt_toggle_offset_sequence_reqd(frm);
	},
});

function alt_toggle_offset_sequence_reqd(frm) {
	const apply = (company_values) => {
		ALT_COMPANY_OFFSET_FIELDS.forEach((field) => {
			const company_value = company_values[field];
			frm.toggle_reqd(field, !company_value);
			frm.set_df_property(
				field,
				"description",
				company_value
					? __("Leave blank to use the Company's {0}.", [`<b>${frappe.utils.escape_html(company_value)}</b>`])
					: __("Required: not set on the Company.")
			);
		});
	};

	if (!frm.doc.company) {
		apply({});
		return;
	}
	frappe.db
		.get_value("Company", frm.doc.company, ALT_COMPANY_OFFSET_FIELDS)
		.then((r) => apply((r && r.message) || {}));
}

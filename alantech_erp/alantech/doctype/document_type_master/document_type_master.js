// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

// Example for each Number Format (same as FORMATS in document/document_number.py)
const ALT_NUMBER_EXAMPLES = {
	Aadhaar: "2345 6789 0124",
	PAN: "ABCPE1234F",
	"Indian Passport": "A1234567",
	"Indian Driving Licence": "KL07 20110012345",
	"Emirates ID": "784-1990-1234567-6",
};

frappe.ui.form.on("Document Type Master", {
	number_format(frm) {
		frm.set_value("number_example", ALT_NUMBER_EXAMPLES[frm.doc.number_format] || "");
	},
});

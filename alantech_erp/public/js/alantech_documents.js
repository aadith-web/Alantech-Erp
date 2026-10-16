(() => {
	const DOC = "Document";
	const SKIP_MODULES = new Set(["Core", "Custom", "Desk", "Email", "Integrations", "Printing",
		"Website", "Workflow", "Automation", "Social", "Geo", "Contacts"]);

	function add_documents_menu(frm) {
		if (!frm || !frm.doc || frm.is_new() || frm.doctype === DOC) return;
		const meta = frm.meta || {};
		if (meta.istable || meta.issingle || SKIP_MODULES.has(meta.module)) return;
		if (!frappe.model.can_read(DOC)) return;

		const group = __("Documents");
		const opts = { reference_doctype: frm.doctype, reference_name: frm.doc.name };
		frm.add_custom_button(__("View"), () => frappe.set_route("List", DOC, opts), group);
		if (frappe.model.can_create(DOC)) {
			frm.add_custom_button(__("Add"), () => frappe.new_doc(DOC, opts), group);
		}
	}

	// Frappe fires this on every form refresh, in every app
	$(document).on("form-refresh", (e, frm) => add_documents_menu(frm));
})();

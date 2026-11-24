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

	// Rename (pencil) button in the form sidebar, next to print / like, for doctypes that allow rename
	// (e.g. Gender: only an ID column). Reuses Frappe's own rename dialog; nothing in core is changed.
	function add_sidebar_rename(frm) {
		if (!frm || !frm.doc || frm.is_new() || frm.meta?.istable) return;
		if (!frm.meta?.allow_rename || !frm.perm?.[0]?.write) return;

		const $side = $(frm.wrapper).find(".form-sidebar").first();
		if (!$side.length) return;
		// User (and others) already show an edit icon; do not add a second one
		if ($side.find(".al-sidebar-rename, .sidebar-rename, .edit-profile-btn, .icon-edit, use[href*='icon-edit']").length) return;

		const $btn = $(`<button class="btn btn-default btn-xs icon-btn al-sidebar-rename" title="${__("Rename")}">
			${frappe.utils.icon("edit", "sm")}</button>`);
		$btn.on("click", () => frm.rename_doc?.() || frm.toolbar?.rename_document_title?.());

		const $anchor = $side.find(".form-print-icon, .print-icon, .like-icon, .liked-by").first();
		if ($anchor.length) $btn.insertBefore($anchor.closest("button, .icon-btn, .like-icon").length ? $anchor.closest("button, .icon-btn, .like-icon") : $anchor);
		else $side.find(".sidebar-section, .form-sidebar-top").first().prepend($btn);
	}

	// Frappe fires this on every form refresh, in every app
	$(document).on("form-refresh", (e, frm) => {
		add_documents_menu(frm);
		add_sidebar_rename(frm);
	});
})();
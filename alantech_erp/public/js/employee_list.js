// Employee list: upload a Document for an employee without opening the employee first.
// Loaded through doctype_list_js in hooks.py. Extends ERPNext's own Employee list settings
// (status colours, "Import Employees" button) instead of replacing them.

(() => {
	const DOC = "Document";
	const settings = (frappe.listview_settings["Employee"] = frappe.listview_settings["Employee"] || {});

	// 1. "Upload Document" button on the list toolbar + in the Actions menu for a selected row
	const erpnext_onload = settings.onload;
	settings.onload = function (listview) {
		if (erpnext_onload) erpnext_onload.call(this, listview);
		keep_department_tree_filter(listview);
		if (!frappe.model.can_create(DOC)) return;

		listview.page.add_inner_button(__("Upload Document"), () => {
			const selected = listview.get_checked_items(true);
			alt_upload_document(selected.length === 1 ? selected[0] : null);
		});

		listview.page.add_actions_menu_item(
			__("Upload Document"),
			() => {
				const selected = listview.get_checked_items(true);
				if (selected.length !== 1) {
					frappe.msgprint(__("Select one employee to upload a document for."));
					return;
				}
				alt_upload_document(selected[0]);
			},
			false
		);
	};

	// 2. "Upload" button on every row
	if (!settings.button) {
		settings.button = {
			show: () => frappe.model.can_create(DOC),
			get_label: () => __("Upload"),
			get_description: (doc) => __("Upload a document for {0}", [doc.employee_name || doc.name]),
			action: (doc) => alt_upload_document(doc.name),
		};
	}

	// Department filter must always include sub-departments ("All Departments" = everyone).
	// Frappe switches it to an exact "=" match for good once a department filter comes from the
	// URL or the saved list settings, after which a parent department finds nobody.
	function keep_department_tree_filter(listview) {
		const field = listview.page.fields_dict.department;
		if (!field || !field.df.condition) return;
		Object.defineProperty(field.df, "match_type", {
			get: () => field.df.condition,
			set: () => {},
			configurable: true,
		});
		if (field.get_value()) listview.refresh();
	}

	// Ask for employee + document type, then open a pre-filled Document form
	function alt_upload_document(employee) {
		const dialog = new frappe.ui.Dialog({
			title: __("Upload Document"),
			fields: [
				{
					fieldname: "employee",
					fieldtype: "Link",
					label: __("Employee"),
					options: "Employee",
					reqd: 1,
					default: employee || undefined,
					get_query: () => ({ filters: { status: "Active" } }),
					onchange: () => show_name(),
				},
				{
					fieldname: "employee_name",
					fieldtype: "Data",
					label: __("Employee Name"),
					read_only: 1,
				},
				{
					fieldname: "document_type",
					fieldtype: "Link",
					label: __("Document Type"),
					options: "Document Type Master",
					reqd: 1,
					get_query: () => ({ filters: { disabled: 0 } }),
				},
			],
			primary_action_label: __("Continue"),
			primary_action(values) {
				dialog.hide();
				frappe.new_doc(DOC, {
					reference_doctype: "Employee",
					reference_name: values.employee,
					document_type: values.document_type,
				});
			},
		});

		function show_name() {
			const emp = dialog.get_value("employee");
			if (!emp) return dialog.set_value("employee_name", "");
			frappe.db.get_value("Employee", emp, "employee_name").then((r) => {
				dialog.set_value("employee_name", (r.message && r.message.employee_name) || "");
			});
		}

		dialog.show();
		show_name();
	}
})();
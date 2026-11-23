// "Assign asset" on the Employee profile (HRMS AssetsSection.vue) builds an unsaved Asset Movement
// with purpose Issue and routes to it. Alantech issues assets through Employee Asset Handover
// instead, so send that click to a new handover for the same employee. HRMS itself is untouched.
(() => {
	if (frappe.__alantech_assign_override) return;
	frappe.__alantech_assign_override = true;

	const original = frappe.set_route;

	frappe.set_route = function (...args) {
		const route = args.length === 1 && Array.isArray(args[0]) ? args[0] : args;
		if (route[0] !== "Form" || route[1] !== "Asset Movement" || !route[2]) {
			return original.apply(this, args);
		}

		let movement;
		try {
			movement = frappe.get_doc("Asset Movement", route[2]);
		} catch (e) {
			return original.apply(this, args);
		}

		// only the unsaved movement the profile button makes: a new Issue with one employee row
		// and no link to a request or another document
		const row = (movement && movement.assets) || [];
		const isAssignClick =
			movement &&
			movement.__islocal &&
			movement.purpose === "Issue" &&
			!movement.reference_doctype &&
			row.length === 1 &&
			row[0].to_employee &&
			!row[0].asset;

		if (!isAssignClick) {
			return original.apply(this, args);
		}

		const employee = row[0].to_employee;
		const company = movement.company;
		frappe.model.clear_doc("Asset Movement", movement.name);
		frappe.new_doc("Employee Asset Handover", { transaction_type: "Issue", employee, company });
	};
})();

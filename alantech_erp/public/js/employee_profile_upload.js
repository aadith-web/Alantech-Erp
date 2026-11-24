// Employee profile > Documents: Upload / Replace open a new Document (reference: this Employee,
// Document Type: the row's type) instead of hrms's upload dialog. The profile is hrms's island
// in a shadow root, so this listens in the capture phase on window and stops the click before
// the island's own handler. Nothing in hrms or alantech_branding is edited.

const FORM_PATH = "/hr-setup/employee/";
const ACTIONS = ["Upload", "Replace"];

function employeeFromPath() {
	const at = window.location.pathname.indexOf(FORM_PATH);
	if (at < 0) return null;
	const name = window.location.pathname.slice(at + FORM_PATH.length).split("/")[0];
	return name ? decodeURIComponent(name) : null;
}

// The row holds exactly one button (its Upload / Replace). The first line of its text is the
// Document Type, then the details and the status badge.
function rowDocumentType(button) {
	let row = button;
	for (let node = button.parentElement; node; node = node.parentElement) {
		if (node.querySelectorAll("button").length > 1) break;
		row = node;
	}
	const line = (row.innerText || "")
		.split("\n")
		.map((text) => text.trim())
		.find((text) => text && !ACTIONS.includes(text));
	return line || null;
}

(function initEmployeeProfileUpload() {
	if (window.__alantechProfileUpload) return;
	window.__alantechProfileUpload = true;

	window.addEventListener(
		"click",
		(e) => {
			const path = e.composedPath ? e.composedPath() : [];
			const button = path.find((node) => node.tagName === "BUTTON");
			if (!button || !ACTIONS.includes((button.textContent || "").trim())) return;

			const section = button.closest ? button.closest("section") : null;
			if (!section || !(section.textContent || "").trim().startsWith("Documents")) return;

			const employee = employeeFromPath();
			if (!employee || !window.frappe || !frappe.new_doc) return;

			e.preventDefault();
			e.stopImmediatePropagation();
			frappe.new_doc("Document", {
				reference_doctype: "Employee",
				reference_name: employee,
				document_type: rowDocumentType(button) || undefined,
			});
		},
		true
	);
})();

// Employee profile > Documents: the row menu has no "Upload for them" / "Replace for them" item.
// The menu is rendered inside hrms's shadow-root island (and may be portalled to body), so this
// walks every open shadow root and hides the item whenever the page changes. Only on the Employee
// form path. "Ask for it again" and "Remove" stay.
(function initHideUploadForThem() {
	if (window.__alantechHideUploadForThem) return;
	window.__alantechHideUploadForThem = true;

	const HIDDEN_LABELS = ["Upload for them", "Replace for them"];
	let scheduled = false;

	function allRoots(root, roots) {
		roots.push(root);
		for (const el of root.querySelectorAll("*")) {
			if (el.shadowRoot) allRoots(el.shadowRoot, roots);
		}
		return roots;
	}

	function hideItems() {
		scheduled = false;
		if (!employeeFromPath()) return;
		for (const root of allRoots(document, [])) {
			for (const el of root.querySelectorAll("button, [role='menuitem'], a, li, div, span")) {
				const text = (el.textContent || "").trim();
				if (!HIDDEN_LABELS.includes(text)) continue;
				// hide the item itself, not the text node's wrapper that holds other rows
				const item = el.closest("[role='menuitem'], button, a, li") || el;
				if (item.style.display !== "none") item.style.display = "none";
			}
		}
	}

	function schedule() {
		if (scheduled) return;
		scheduled = true;
		requestAnimationFrame(hideItems);
	}

	new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
	schedule();
})();

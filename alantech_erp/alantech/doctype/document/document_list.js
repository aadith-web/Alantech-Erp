// Inactive/Left employees' documents are already filtered out on the server
frappe.listview_settings["Document"] = {
	add_fields: ["approval_status", "document_type", "expiry_date", "reference_doctype"],

	get_indicator(doc) {
		const colours = { "Pending Approval": "orange", Approved: "green", Rejected: "red" };
		if (!doc.approval_status) return;
		return [__(doc.approval_status), colours[doc.approval_status] || "gray",
		        `approval_status,=,${doc.approval_status}`];
	},

	// Expiring soon / expired banner above the list (ClickUp 14yr2e58g46): the documents the user can
	// see (employee: own, "Your Passport ..."), wording and window from document_expiry_warning.py
	refresh(listview) {
		alt_doc_expiry_banner(listview);
	},

	formatters: {
		expiry_date(value) {
			if (!value) return "";
			const days = frappe.datetime.get_day_diff(value, frappe.datetime.get_today());
			const text = frappe.datetime.str_to_user(value);
			if (days < 0) return `<span class="text-danger">${text}</span>`;
			if (days <= 30) return `<span class="text-warning">${text}</span>`;
			return text;
		},
	},
};

const ALT_DOC_BANNER_MAX = 5;

function alt_doc_expiry_banner(listview) {
	const $parent = listview.$frappe_list || listview.page.main;
	frappe
		.xcall("alantech_erp.alantech.doctype.document.document_expiry_warning.get_expiry_warnings")
		.then((rows) => {
			$parent.find(".alt-doc-expiry-banner").remove();
			alt_doc_expiry_pills(listview, rows || []);
			if (!rows || !rows.length) return;
			const esc = frappe.utils.escape_html;
			const expired = rows.filter((r) => r.status === "expired").length;
			const soon = rows.length - expired;
			const heading = [
				expired ? __("{0} expired", [expired]) : "",
				soon ? __("{0} expiring soon", [soon]) : "",
			].filter(Boolean).join(" · ");
			const items = rows.slice(0, ALT_DOC_BANNER_MAX).map((r) =>
				`<li><a href="/desk/document/${encodeURIComponent(r.name)}" class="${r.status === "expired" ? "text-danger" : ""}">
					${esc(r.message)}</a> <span class="text-muted">(${esc(r.name)})</span></li>`).join("");
			const more = rows.length > ALT_DOC_BANNER_MAX
				? `<div class="text-muted small">${__("and {0} more", [rows.length - ALT_DOC_BANNER_MAX])}</div>` : "";
			const colour = expired ? "red" : "yellow";
			$(`<div class="alt-doc-expiry-banner form-message ${colour}" style="margin: var(--margin-sm) var(--margin-md); border-radius: var(--border-radius);">
					<div><b>${__("Documents to update")}: ${heading}</b></div>
					<ul style="margin: var(--margin-xs) 0 0; padding-left: 18px;">${items}</ul>${more}
				</div>`).prependTo($parent);
		})
		.catch(() => {});
}

// "Expiring Soon" / "Expired" next to the approval status of the rows shown
function alt_doc_expiry_pills(listview, rows) {
	const esc = frappe.utils.escape_html;
	listview.$result.find(".alt-doc-expiry-pill").remove();
	rows.forEach((r) => {
		const $row = listview.$result
			.find(".list-row-checkbox")
			.filter((_, el) => $(el).attr("data-name") === r.name)
			.closest(".list-row");
		const $status = $row.find(".indicator-pill").first();
		if (!$status.length) return;
		$(`<span class="indicator-pill ${r.status === "expired" ? "red" : "orange"} alt-doc-expiry-pill"
			style="margin-left:4px;" title="${esc(r.message)}">
			${r.status === "expired" ? __("Expired") : __("Expiring Soon")}</span>`).insertAfter($status);
	});
}

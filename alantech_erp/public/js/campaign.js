// Campaign (CRM C24, C36): owner, budget and costs, child campaigns, and the campaign's results.
// The Leads / Customers / Deals / Quotations / Sales Orders of a campaign link to its UTM Campaign
// (ERPNext keeps one per Campaign); the View buttons open them filtered on it.
// Server side: alantech_erp/sales/campaign.py
frappe.ui.form.on("Campaign", {
	setup(frm) {
		frm.set_query("alt_parent_campaign", () => ({
			filters: [
				["Campaign", "name", "!=", frm.doc.name || ""],
				["Campaign", "alt_status", "!=", "Cancelled"],
			],
		}));
	},

	refresh(frm) {
		if (frm.is_new()) return;

		// ERPNext's own "View Leads" button: replaced by the View menu below
		setTimeout(() => frm.remove_custom_button(__("View Leads")), 0);

		const view = (doctype, field) => () =>
			frappe
				.call("alantech_erp.sales.campaign.get_utm_campaign", { campaign: frm.doc.name })
				.then(({ message }) => {
					frappe.route_options = { [field]: message };
					frappe.set_route("List", doctype);
				});
		[
			["Lead", "utm_campaign"],
			["Customer", "alt_campaign"],
			["Opportunity", "utm_campaign"],
			["Quotation", "utm_campaign"],
			["Sales Order", "utm_campaign"],
		].forEach(([doctype, field]) => {
			const label = doctype === "Opportunity" ? __("Deals") : __(doctype);
			frm.add_custom_button(label, view(doctype, field), __("View"));
		});
		frm.add_custom_button(
			__("Campaign ROI"),
			() =>
				frappe.set_route("query-report", "Campaign ROI", {
					company: frm.doc.alt_company,
					campaign: frm.doc.name,
				}),
			__("View")
		);

		if (frappe.model.can_create("Campaign") && frm.doc.alt_status !== "Cancelled") {
			frm.add_custom_button(
				__("Child Campaign"),
				() =>
					frappe.new_doc("Campaign", {
						alt_parent_campaign: frm.doc.name,
						alt_company: frm.doc.alt_company,
						alt_campaign_type: frm.doc.alt_campaign_type,
					}),
				__("Create")
			);
		}

		show_results(frm);
	},

	alt_start_date(frm) {
		check_dates(frm);
	},

	alt_end_date(frm) {
		check_dates(frm);
	},
});

frappe.ui.form.on("Campaign Cost", {
	amount(frm) {
		set_actual_cost(frm);
	},
	alt_costs_remove(frm) {
		set_actual_cost(frm);
	},
});

function set_actual_cost(frm) {
	const total = (frm.doc.alt_costs || []).reduce((sum, row) => sum + flt(row.amount), 0);
	frm.set_value("alt_actual_cost", flt(total, 2));
}

function check_dates(frm) {
	const { alt_start_date: start, alt_end_date: end } = frm.doc;
	if (start && end && frappe.datetime.str_to_obj(end) < frappe.datetime.str_to_obj(start)) {
		frappe.msgprint(__("The End Date cannot be before the Start Date."));
		frm.set_value("alt_end_date", null);
	}
}

function show_results(frm) {
	frappe
		.call("alantech_erp.sales.campaign.get_campaign_summary", { campaign: frm.doc.name })
		.then(({ message: s }) => {
			if (!s || frm.doc.name !== frm.docname) return;
			const money = (v) => format_currency(v || 0, s.currency);
			const pct = (v) => `${flt(v, 2)}%`;
			const rows = [
				[__("Leads"), "leads", cint],
				[__("Customers"), "customers", cint],
				[__("Deals"), "deals", cint],
				[__("Quotations Sent"), "quotations", cint],
				[__("Sales Orders"), "sales_orders", cint],
				[__("Budget"), "budget", money],
				[__("Actual Cost"), "actual_cost", money],
				[__("Income (Sales Orders)"), "income", money],
				[__("Profit"), "profit", money],
				[__("ROI"), "roi", pct],
				[__("Cost per Lead"), "cost_per_lead", money],
				[__("Win Rate (Orders / Quotations)"), "win_rate", pct],
			];
			const with_children = s.children > 0;
			const head = with_children
				? `<th></th><th class="text-right">${__("This Campaign")}</th>
				   <th class="text-right">${__("Incl. {0} Child Campaign(s)", [s.children])}</th>`
				: `<th></th><th class="text-right">${__("This Campaign")}</th>`;
			const body = rows
				.map(([label, key, fmt]) => {
					const own = `<td class="text-right">${fmt(s.own[key])}</td>`;
					const total = with_children ? `<td class="text-right"><b>${fmt(s.total[key])}</b></td>` : "";
					return `<tr><td>${label}</td>${own}${total}</tr>`;
				})
				.join("");
			const html = `<table class="table table-sm table-bordered" style="margin:0">
				<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

			frm.dashboard.clear_headline();
			frm.dashboard.add_section(html, __("Campaign Results"));
			const total = with_children ? s.total : s.own;
			if (flt(total.budget) && flt(total.actual_cost) > flt(total.budget)) {
				frm.dashboard.set_headline(
					__("Over budget: actual cost {0} against a budget of {1}.", [
						money(total.actual_cost),
						money(total.budget),
					]),
					"orange"
				);
			}
			if (!s.utm_campaign) {
				frm.dashboard.set_headline(
					__("No UTM Campaign is linked to this campaign yet, so no documents are counted. Save the campaign once to create it."),
					"red"
				);
			}
		});
}

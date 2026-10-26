// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

const ALT_FILL_RE = /\[\[([\s\S]*?)\]\]/g;
const ALT_EST = "alantech_erp.alantech.doctype.estimation.estimation";

// Fields that may hold [[ ]] (same list as alantech_erp/proposal/__init__.py)
const ALT_OFFER_TEXT_FIELDS = [
	"project_name", "project_location", "subject", "kind_attn", "your_ref",
	"intro_text", "water_analysis_intro", "water_analysis_remarks",
	"scope_of_supply", "commercial_terms", "bank_details", "price_heading", "price_notes",
];
const ALT_OFFER_TABLE_FIELDS = {
	guarantees: ["parameter", "value", "unit"],
	project_data: ["parameter", "value", "unit"],
	water_analysis: ["parameter", "value", "unit"],
	sections: ["description", "specs", "notes"],
	components: ["qty_label", "title", "description", "specs", "notes"],
	price_lines: ["description"],
};
const ALT_HTML_FIELDS = new Set([
	"intro_text", "water_analysis_intro", "water_analysis_remarks", "scope_of_supply",
	"commercial_terms", "price_notes", "description", "notes",
]);

frappe.ui.form.on("Technical Offer", {
	setup(frm) {
		frm.set_query("plant_assembly", () => ({ filters: { disabled: 0 } }));
		frm.set_query("estimation", () => ({
			filters: { docstatus: ["<", 2], ...(frm.doc.opportunity ? { opportunity: frm.doc.opportunity } : {}) },
		}));
		frm.set_query("sub_assembly", "sections", () => ({ filters: { disabled: 0 } }));
		["scope_of_supply_terms", "commercial_terms_template"].forEach((f) =>
			frm.set_query(f, () => ({ filters: { disabled: 0 } }))
		);
	},

	refresh(frm) {
		sync_section_options(frm);
		show_fill_status(frm);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Fill In Values"), () => fill_in_values(frm));
			frm.add_custom_button(__("Add Sub Assembly"), () => add_sub_assembly(frm), __("Sections"));
			if (frm.doc.estimation) {
				frm.add_custom_button(__("Update Prices from Estimation"), () => fetch_prices(frm), __("Sections"));
			}
		}

		if (frm.doc.docstatus === 1 && frm.doc.estimation && frappe.model.can_create("Quotation")) {
			frappe.db.get_value("Estimation", frm.doc.estimation, "docstatus").then(({ message }) => {
				if (!message || message.docstatus !== 1) return;
				frm.add_custom_button(
					__("Quotation"),
					() =>
						frappe.model.open_mapped_doc({
							method: `${ALT_EST}.make_quotation`,
							source_name: frm.doc.estimation,
							args: { technical_offer: frm.doc.name },
						}),
					__("Create")
				);
			});
		}
	},

	plant_assembly(frm) {
		if (!frm.doc.plant_assembly || frm.doc.docstatus !== 0) return;
		const has_sections = (frm.doc.sections || []).length;
		const load = (keep_sections) =>
			frm.call("apply_plant_assembly", { keep_sections: keep_sections ? 1 : 0 }).then(() => {
				frm.dirty();
				sync_section_options(frm);
				frm.refresh_fields();
				show_fill_status(frm);
			});
		if (!has_sections) return load(false);

		const d = new frappe.ui.Dialog({
			title: __("Load Plant Assembly"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${__("Load the standard text, design basis tables and terms of {0}.", [
						`<b>${frappe.utils.escape_html(frm.doc.plant_assembly)}</b>`,
					])}</p>`,
				},
				{ fieldname: "replace_sections", fieldtype: "Check", label: __("Also replace the sections and components") },
			],
			primary_action_label: __("Load"),
			primary_action(values) {
				d.hide();
				load(!values.replace_sections);
			},
		});
		d.show();
	},

	estimation(frm) {
		if (!frm.doc.estimation) return;
		frappe.db
			.get_value("Estimation", frm.doc.estimation, ["opportunity", "customer_name", "company", "currency"])
			.then(({ message }) => {
				if (!message) return;
				["opportunity", "customer_name", "company", "currency"].forEach((f) => {
					if (!frm.doc[f] && message[f]) frm.set_value(f, message[f]);
				});
			});
	},

	scope_of_supply_terms(frm) {
		set_terms(frm, "scope_of_supply_terms", "scope_of_supply");
	},

	commercial_terms_template(frm) {
		set_terms(frm, "commercial_terms_template", "commercial_terms");
	},
});

frappe.ui.form.on("Technical Offer Section", {
	section_title(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const old_title = (frm._alt_section_titles || {})[cdn];
		if (old_title && row.section_title && old_title !== row.section_title) {
			(frm.doc.components || []).forEach((c) => {
				if (c.section === old_title) c.section = row.section_title;
			});
		}
		sync_section_options(frm);
	},
	sections_remove(frm) {
		const titles = new Set((frm.doc.sections || []).map((s) => s.section_title));
		const before = (frm.doc.components || []).length;
		frm.doc.components = (frm.doc.components || []).filter((c) => !c.section || titles.has(c.section));
		frm.doc.components.forEach((c, i) => (c.idx = i + 1));
		const removed = before - frm.doc.components.length;
		if (removed) {
			frappe.show_alert({ message: __("Removed {0} components of the deleted section", [removed]), indicator: "orange" });
		}
		sync_section_options(frm);
	},
});

frappe.ui.form.on("Offer Component", {
	components_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const rows = frm.doc.components || [];
		const prev = rows[rows.length - 2];
		const sections = frm.doc.sections || [];
		row.section = (prev && prev.section) || (sections.length ? sections[sections.length - 1].section_title : "");
		frm.refresh_field("components");
	},
});

frappe.ui.form.on("Technical Offer Price Line", {
	amount: calculate_totals,
	pricing_mode: calculate_totals,
	price_lines_remove: calculate_totals,
});

function calculate_totals(frm) {
	const t = { Included: 0, "Separate Line": 0, Optional: 0 };
	(frm.doc.price_lines || []).forEach((r) => (t[r.pricing_mode || "Included"] += flt(r.amount)));
	frm.set_value({
		main_total: t.Included,
		separate_total: t["Separate Line"],
		optional_total: t.Optional,
		grand_total: t.Included + t["Separate Line"],
	});
}

function sync_section_options(frm) {
	const titles = (frm.doc.sections || []).map((s) => s.section_title).filter(Boolean);
	frm.fields_dict.components.grid.update_docfield_property("section", "options", [""].concat(titles));
	frm._alt_section_titles = {};
	(frm.doc.sections || []).forEach((s) => (frm._alt_section_titles[s.name] = s.section_title));
	frm.refresh_field("components");
}

function set_terms(frm, template_field, text_field) {
	const template = frm.doc[template_field];
	if (!template) return;
	frappe
		.call({
			method: "erpnext.setup.doctype.terms_and_conditions.terms_and_conditions.get_terms_and_conditions",
			args: { template_name: template, doc: frm.doc },
		})
		.then(({ message }) => frm.set_value(text_field, message || ""));
}

function add_sub_assembly(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Add Sub Assembly"),
		fields: [
			{
				fieldname: "sub_assembly",
				fieldtype: "Link",
				options: "Sub Assembly",
				label: __("Sub Assembly"),
				reqd: 1,
				get_query: () => ({ filters: { disabled: 0 } }),
				onchange() {
					const name = dialog.get_value("sub_assembly");
					if (!name) return;
					frappe.db.get_value("Sub Assembly", name, "offer_title").then(({ message }) => {
						dialog.set_value("section_title", (message && message.offer_title) || name);
					});
				},
			},
			{ fieldname: "section_title", fieldtype: "Data", label: __("Section Title") },
		],
		primary_action_label: __("Add"),
		primary_action(values) {
			frm.call("add_sub_assembly", values).then(() => {
				dialog.hide();
				frm.dirty();
				sync_section_options(frm);
				frm.refresh_fields();
				show_fill_status(frm);
			});
		},
	});
	dialog.show();
}

function fetch_prices(frm) {
	const go = () =>
		frm.call("fetch_prices").then(() => {
			frm.dirty();
			frm.refresh_fields();
			frappe.show_alert({ message: __("Price schedule updated from {0}", [frm.doc.estimation]), indicator: "green" });
		});
	if ((frm.doc.price_lines || []).length) {
		frappe.confirm(__("Replace the price schedule with the prices of Estimation {0}?", [frm.doc.estimation]), go);
	} else {
		go();
	}
}

// ---------------------------------------------------------------- [[ ]] values
function strip_tags(text) {
	return (text || "").replace(/<[^>]*>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
}

function collect_placeholders(frm) {
	// one entry per [[ ]], in document order: {doc, field, label, hint, group}
	const found = [];
	const scan = (doc, field, label, group) => {
		const text = doc[field];
		if (!text || typeof text !== "string" || !text.includes("[[")) return;
		if (field === "specs") {
			text.split("\n").forEach((line) => {
				const param = line.split("|")[0].trim();
				(line.match(ALT_FILL_RE) || []).forEach((m) =>
					found.push({ doc, field, group, label: `${label} › ${param}`, hint: strip_tags(m.slice(2, -2)) })
				);
			});
			return;
		}
		(text.match(ALT_FILL_RE) || []).forEach((m) => {
			const context = ALT_HTML_FIELDS.has(field) ? around(strip_tags(text), strip_tags(m)) : "";
			found.push({ doc, field, group, label: context ? `${label}: ${context}` : label, hint: strip_tags(m.slice(2, -2)) });
		});
	};

	ALT_OFFER_TEXT_FIELDS.forEach((f) => scan(frm.doc, f, __(frappe.meta.get_label(frm.doctype, f)), __("Offer")));
	Object.entries(ALT_OFFER_TABLE_FIELDS).forEach(([table, fields]) => {
		(frm.doc[table] || []).forEach((row) => {
			let group = __(frappe.meta.get_label(frm.doctype, table));
			let label = row.parameter || row.section_title || row.description || "";
			if (table === "components") {
				group = row.section || group;
				label = `${row.qty_label || ""} ${row.title || ""}`.trim();
			}
			fields.forEach((f) => scan(row, f, strip_tags(label) || `#${row.idx}`, group));
		});
	});
	return found;
}

function around(text, marker) {
	// a few words before the [[ ]] so the engineer knows which value it is
	const i = text.indexOf(marker);
	if (i < 0) return "";
	const before = text.slice(Math.max(0, i - 45), i).trim();
	return (before ? "…" + before + " " : "") + "[ ]";
}

function show_fill_status(frm) {
	if (frm.doc.docstatus !== 0) return;
	const n = collect_placeholders(frm).length;
	if (n) {
		frm.set_intro(
			__("{0} values are still to be filled in (marked [[ ]]). Click Fill In Values to complete them; the offer cannot be submitted until they are done.", [n]),
			"orange"
		);
	} else {
		frm.set_intro("");
	}
}

function fill_in_values(frm) {
	const found = collect_placeholders(frm);
	if (!found.length) {
		frappe.msgprint(__("Nothing to fill in. All [[ ]] values are complete."));
		return;
	}
	const fields = [];
	let group = null;
	found.forEach((p, i) => {
		if (p.group !== group) {
			group = p.group;
			fields.push({ fieldtype: "Section Break", label: group, collapsible: 0 });
		}
		fields.push({ fieldname: `v${i}`, fieldtype: "Data", label: p.label, default: p.hint });
	});

	const dialog = new frappe.ui.Dialog({
		title: __("Fill In Values ({0})", [found.length]),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"Each box shows the standard value. Change it where needed; leave a box empty to keep it open for later."
				)}</p>`,
			},
			...fields,
		],
		primary_action_label: __("Apply"),
		primary_action(values) {
			// replace in each text field, occurrences in order
			const by_target = new Map();
			found.forEach((p, i) => {
				const key = `${p.doc.doctype}|${p.doc.name}|${p.field}`;
				if (!by_target.has(key)) by_target.set(key, { p, values: [] });
				by_target.get(key).values.push(values[`v${i}`]);
			});
			by_target.forEach(({ p, values: vals }) => {
				let k = 0;
				p.doc[p.field] = p.doc[p.field].replace(ALT_FILL_RE, (m) => {
					const v = (vals[k++] || "").trim();
					if (!v) return m;
					return ALT_HTML_FIELDS.has(p.field) ? frappe.utils.escape_html(v) : v;
				});
			});
			dialog.hide();
			frm.dirty();
			frm.refresh_fields();
			show_fill_status(frm);
			const left = collect_placeholders(frm).length;
			frappe.show_alert({
				message: left ? __("{0} values still open", [left]) : __("All values filled in. Save the offer."),
				indicator: left ? "orange" : "green",
			});
		},
	});
	dialog.show();
}

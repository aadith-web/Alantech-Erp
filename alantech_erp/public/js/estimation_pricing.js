// Live costing for the Estimation form (same formulas as estimation.py calculate_pricing).
// Loaded through doctype_js in hooks.py; the guard keeps handlers from being added twice.

frappe.provide("alantech.estimation");

if (!alantech.estimation.loaded) {
	alantech.estimation.loaded = true;

	const OPTIONAL = "Optional";
	const SEPARATE = "Separate Line";

	alantech.estimation.apply_margin = function (cost, margin, basis, round_to) {
		let price =
			basis === "Margin on Selling Price"
				? flt(margin) < 100
					? cost / (1 - flt(margin) / 100)
					: 0
				: cost * (1 + flt(margin) / 100);
		const step = cint(round_to);
		if (step > 1 && price) price = Math.round(price / step) * step;
		return price;
	};

	alantech.estimation.calculate = function (frm) {
		const doc = frm.doc;
		const sections = {};
		(doc.sections || []).forEach((s) => {
			s.amount = s.addon_amount = s.total_cost = 0;
			sections[s.section_title] = s;
		});

		(doc.items || []).forEach((row) => {
			row.amount = flt(flt(row.qty) * flt(row.unit_cost), precision("amount", row));
			row.addon_amount = flt((row.amount * flt(row.addon_pct)) / 100, precision("addon_amount", row));
			row.total_cost = flt(row.amount + row.addon_amount, precision("total_cost", row));
			const s = sections[row.section];
			if (s) {
				s.amount += row.amount;
				s.addon_amount += row.addon_amount;
				s.total_cost += row.total_cost;
			}
		});

		const t = { amount: 0, addon: 0, cost: 0, Equipment: 0, Manpower: 0, Other: 0 };
		Object.values(sections).forEach((s) => {
			if (s.pricing_mode === OPTIONAL) return;
			t.amount += s.amount;
			t.addon += s.addon_amount;
			t.cost += s.total_cost;
			t[["Equipment", "Manpower"].includes(s.cost_type) ? s.cost_type : "Other"] += s.total_cost;
		});

		const contingency = (t.cost * flt(doc.contingency_pct)) / 100;
		const financing = (t.cost * flt(doc.financing_pct)) / 100;
		const cost_price = t.cost + contingency + (cint(doc.include_financing) ? financing : 0);
		const load = t.cost
			? cost_price / t.cost
			: 1 + (flt(doc.contingency_pct) + (cint(doc.include_financing) ? flt(doc.financing_pct) : 0)) / 100;

		let main = 0;
		let separate = 0;
		let optional = 0;
		Object.values(sections).forEach((s) => {
			const margin = cint(s.override_margin) ? flt(s.margin_pct) : flt(doc.profit_pct);
			s.selling_price = flt(
				alantech.estimation.apply_margin(s.total_cost * load, margin, doc.margin_basis, doc.round_to),
				precision("selling_price", s)
			);
			if (s.pricing_mode === OPTIONAL) optional += s.selling_price;
			else if (s.pricing_mode === SEPARATE) separate += s.selling_price;
			else main += s.selling_price;
		});

		const selling = main + separate;
		const commission = (selling * flt(doc.sales_commission_pct)) / 100;
		const profit = selling - cost_price - commission;

		Object.assign(doc, {
			total_amount: t.amount,
			total_addon: t.addon,
			total_cost: t.cost,
			equipment_cost: t.Equipment,
			manpower_cost: t.Manpower,
			general_cost: t.Other,
			contingency_amount: contingency,
			financing_amount: financing,
			cost_price: cost_price,
			main_price: main,
			selling_price: selling,
			optional_price: optional,
			sales_commission_amount: commission,
			profit_amount: profit,
			profit_on_cost_pct: cost_price ? flt((profit / cost_price) * 100, 2) : 0,
			grand_selling_price: selling * Math.max(cint(doc.no_of_trains), 1),
		});
		frm.refresh_fields();
	};

	// Section dropdown of the cost items = titles in the Sub Assemblies table
	alantech.estimation.sync_sections = function (frm) {
		const titles = (frm.doc.sections || []).map((s) => s.section_title).filter(Boolean);
		frm.fields_dict.items.grid.update_docfield_property("section", "options", [""].concat(titles));
		frm._alt_section_titles = {};
		(frm.doc.sections || []).forEach((s) => (frm._alt_section_titles[s.name] = s.section_title));
		frm.refresh_field("items");
	};

	const recalc = (frm) => alantech.estimation.calculate(frm);

	const header = {};
	[
		"contingency_pct",
		"financing_pct",
		"include_financing",
		"margin_basis",
		"profit_pct",
		"round_to",
		"sales_commission_pct",
		"no_of_trains",
	].forEach((field) => (header[field] = recalc));
	frappe.ui.form.on("Estimation", header);

	frappe.ui.form.on("Estimation Section", {
		section_title(frm, cdt, cdn) {
			// rename the section on its cost items too
			const row = locals[cdt][cdn];
			const old_title = (frm._alt_section_titles || {})[cdn];
			if (old_title && row.section_title && old_title !== row.section_title) {
				(frm.doc.items || []).forEach((item) => {
					if (item.section === old_title) item.section = row.section_title;
				});
			}
			alantech.estimation.sync_sections(frm);
			recalc(frm);
		},
		sub_assembly(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.sub_assembly) return;
			frappe.db
				.get_value("Sub Assembly", row.sub_assembly, ["cost_type", "offer_title", "price_description"])
				.then(({ message }) => {
					if (!message) return;
					const updates = { cost_type: message.cost_type };
					if (!row.section_title) updates.section_title = message.offer_title || row.sub_assembly;
					if (!row.price_description) updates.price_description = message.price_description;
					frappe.model.set_value(cdt, cdn, updates);
				});
		},
		sections_remove(frm) {
			// cost items of a removed section go with it
			const titles = new Set((frm.doc.sections || []).map((s) => s.section_title));
			const before = (frm.doc.items || []).length;
			frm.doc.items = (frm.doc.items || []).filter((item) => !item.section || titles.has(item.section));
			frm.doc.items.forEach((item, i) => (item.idx = i + 1));
			const removed = before - frm.doc.items.length;
			if (removed) {
				frappe.show_alert({ message: __("Removed {0} cost items of the deleted section", [removed]), indicator: "orange" });
			}
			alantech.estimation.sync_sections(frm);
			recalc(frm);
		},
		pricing_mode: recalc,
		cost_type: recalc,
		override_margin: recalc,
		margin_pct: recalc,
	});

	frappe.ui.form.on("Estimation Item", {
		items_add(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			const rows = frm.doc.items || [];
			const prev = rows[rows.length - 2];
			const sections = frm.doc.sections || [];
			if (prev && prev.section) row.section = prev.section;
			else if (sections.length) row.section = sections[sections.length - 1].section_title;
			const section = sections.find((s) => s.section_title === row.section);
			row.addon_pct = section && section.cost_type === "Manpower" ? 0 : flt(frm.doc.default_addon_pct);
			frm.refresh_field("items");
		},
		item_code(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.item_code || flt(row.unit_cost)) return;
			frappe.db.get_value("Item", row.item_code, ["last_purchase_rate", "valuation_rate"]).then(({ message }) => {
				const rate = message && (flt(message.last_purchase_rate) || flt(message.valuation_rate));
				if (rate) frappe.model.set_value(cdt, cdn, "unit_cost", rate);
			});
		},
		items_remove: recalc,
		section: recalc,
		qty: recalc,
		unit_cost: recalc,
		addon_pct: recalc,
	});
}

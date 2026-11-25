// Asset: Create As Grouped Asset / Single Asset (ClickUp 14yr2e58hv1, setup/asset_creation_mode.py).
// Warranty years / months pickers -> Warranty Expiry Date (ClickUp 14yr2e58k7e, setup/asset_warranty.py).
// On a submitted Single Asset: progress of the background creation of the other assets.
// Actions > Split Asset hidden when the Asset Quantity is 1.
const ALT_ASSET_MODE = "alantech_erp.setup.asset_creation_mode";

frappe.ui.form.on("Asset", {
	// Warranty (Years) / (Months) -> Warranty text and Warranty Expiry Date (setup/asset_warranty.py)
	alt_warranty_years(frm) {
		alt_set_warranty_expiry(frm);
		alt_render_warranty_picker(frm);
	},
	alt_warranty_months(frm) {
		alt_set_warranty_expiry(frm);
		alt_render_warranty_picker(frm);
	},
	purchase_date(frm) {
		alt_set_warranty_expiry(frm);
		alt_render_warranty_picker(frm);
	},
	alt_warranty_expiry_date(frm) {
		alt_render_warranty_picker(frm);
	},
	alt_warranty(frm) {
		alt_render_warranty_picker(frm);
	},
	refresh(frm) {
		// nothing to split off an asset of quantity 1 (ERPNext would only refuse it in the dialog)
		if (frm.doc.docstatus === 1 && cint(frm.doc.asset_quantity) <= 1) {
			frm.remove_custom_button(__("Split Asset"), __("Actions"));
		}
		alt_single_asset_status(frm);
		alt_render_warranty_picker(frm);
	},
});

function alt_single_asset_status(frm) {
	if (frm.doc.docstatus !== 1 || frm.doc.alt_asset_creation !== "Single Asset") return;
	frappe.xcall(`${ALT_ASSET_MODE}.get_single_asset_status`, { asset: frm.doc.name }).then((s) => {
		if (!s || s.total < 2) return;
		const done = s.remaining <= 0;
		frm.dashboard.set_headline_alert(
			done
				? __("Single Asset: all {0} assets created (quantity 1 each).", [s.total])
				: __("Single Asset: {0} of {1} assets created; the rest are being created in the background.", [s.created, s.total]),
			done ? "green" : "orange"
		);
		frm.add_custom_button(
			__("Single Assets"),
			() => frappe.set_route("List", "Asset", { split_from: frm.doc.name }),
			__("View")
		);
		if (!done && frm.perm[0] && frm.perm[0].submit) {
			frm.add_custom_button(__("Create Remaining Assets"), () =>
				frappe.xcall(`${ALT_ASSET_MODE}.create_remaining_assets`, { asset: frm.doc.name }).then(() =>
					frappe.show_alert({ message: __("Creating the remaining assets in the background"), indicator: "blue" })
				)
			);
		}
	});
}

function alt_set_warranty_expiry(frm) {
	const years = cint(frm.doc.alt_warranty_years), months = cint(frm.doc.alt_warranty_months);
	if (!years && !months) {
		if (frm.doc.alt_warranty) frm.set_value("alt_warranty", "");
		return;
	}
	const label = [years && `${years} Year${years === 1 ? "" : "s"}`, months && `${months} Month${months === 1 ? "" : "s"}`]
		.filter(Boolean).join(" ");
	if (label !== frm.doc.alt_warranty) frm.set_value("alt_warranty", label);
	if (frm.doc.purchase_date) {
		const expiry = moment(frm.doc.purchase_date).add(years * 12 + months, "months").format("YYYY-MM-DD");
		if (expiry !== frm.doc.alt_warranty_expiry_date) frm.set_value("alt_warranty_expiry_date", expiry);
	}
}

// Warranty picker (ClickUp 14yr2e58k7e): the AlanTech period picker (alantech_branding
// css/common/alantech_period_picker.css): years / months steppers (also typed), quick picks, and a
// status line with the expiry date. Writes the hidden Warranty (Years) / (Months) fields.
const ALT_WARRANTY_PRESETS = [[0, 6, "6 M"], [1, 0, "1 Y"], [2, 0, "2 Y"], [3, 0, "3 Y"], [5, 0, "5 Y"]];
const ALT_WARRANTY_SOON_DAYS = 60;

function alt_warranty_status(frm, years, months) {
	const esc = frappe.utils.escape_html;
	if (!years && !months) return ["empty", __("No warranty. Pick the years and / or months.")];
	const period = `<b>${esc(frm.doc.alt_warranty || "")}</b>`;
	const expiry = frm.doc.alt_warranty_expiry_date;
	if (!expiry) return ["empty", __("{0} warranty. Set the Purchase Date to get the expiry date.", [period])];
	const date = `<b>${frappe.datetime.str_to_user(expiry)}</b>`;
	const days = frappe.datetime.get_day_diff(expiry, frappe.datetime.get_today());
	if (days < 0) return ["expired", __("{0} warranty expired on {1}.", [period, date])];
	if (days <= ALT_WARRANTY_SOON_DAYS) return ["expiring", __("{0} warranty ends on {1} ({2} days left).", [period, date, days])];
	return ["valid", __("{0} warranty, valid till {1}.", [period, date])];
}

function alt_render_warranty_picker(frm) {
	const field = frm.fields_dict.alt_warranty_picker;
	if (!field) return;
	const years = cint(frm.doc.alt_warranty_years), months = cint(frm.doc.alt_warranty_months);
	const editable = frm.doc.docstatus < 2 && frm.perm[0] && (frm.perm[0].write || frm.perm[0].submit);
	const [state, message] = alt_warranty_status(frm, years, months);
	const unit = (name, value, max, label) => `
		<div class="at-period__unit">
			<button type="button" class="at-period__step" data-unit="${name}" data-step="-1"
				${value <= 0 ? "disabled" : ""} aria-label="${__("Less {0}", [label])}">&minus;</button>
			<input class="at-period__num" type="number" min="0" max="${max}" value="${value}" data-unit="${name}"
				aria-label="${label}" ${editable ? "" : "readonly"}>
			<button type="button" class="at-period__step" data-unit="${name}" data-step="1"
				${value >= max ? "disabled" : ""} aria-label="${__("More {0}", [label])}">+</button>
			<span class="at-period__label">${label}</span>
		</div>`;
	const presets = ALT_WARRANTY_PRESETS.map(([y, m, text]) =>
		`<button type="button" class="at-period__preset${y === years && m === months ? " is-active" : ""}"
			data-years="${y}" data-months="${m}">${text}</button>`).join("");

	field.$wrapper.html(`
		<div class="frappe-control">
			<div class="control-label">${__("Warranty")}</div>
			<div class="at-period${editable ? "" : " is-readonly"}">
				<div class="at-period__field">
					${unit("years", years, 30, years === 1 ? __("Year") : __("Years"))}
					<span class="at-period__divider"></span>
					${unit("months", months, 11, months === 1 ? __("Month") : __("Months"))}
				</div>
				<div class="at-period__presets">
					<div class="at-period__group" role="group" aria-label="${__("Quick picks")}">${presets}</div>
					<button type="button" class="at-period__clear" ${years || months ? "" : "disabled"}>${__("Clear")}</button>
				</div>
				<div class="at-period__status at-period__status--${state}">${message}</div>
			</div>
		</div>`);

	if (!editable) return;
	const set = (y, m) => {
		y = Math.max(0, Math.min(30, cint(y)));
		m = Math.max(0, Math.min(11, cint(m)));
		frm.set_value({ alt_warranty_years: y ? String(y) : "", alt_warranty_months: m ? String(m) : "" });
	};
	const $w = field.$wrapper;
	$w.find(".at-period__step").on("click", function () {
		const step = cint($(this).data("step"));
		$(this).data("unit") === "years" ? set(years + step, months) : set(years, months + step);
	});
	$w.find(".at-period__num").on("change", function () {
		$(this).data("unit") === "years" ? set($(this).val(), months) : set(years, $(this).val());
	});
	$w.find(".at-period__preset").on("click", function () {
		set($(this).data("years"), $(this).data("months"));
	});
	$w.find(".at-period__clear").on("click", () => {
		set(0, 0);
		frm.set_value("alt_warranty_expiry_date", "");
	});
}

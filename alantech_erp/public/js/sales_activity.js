// Sales activities on Lead, Customer and Deal (CRM C10): calls, meetings, tasks, notes, emails and
// comments with date, owner and follow-up due date. Loaded on every desk page (app_include_js).
//   Activity menu on the form: Log Call / Schedule Meeting / Add Task / Add Note / Send Email
//   "Activities" panel on the form: pending follow-ups (overdue first), latest activities, counts
// Server side: alantech_erp/sales/activity.py
frappe.provide("alantech.activity");

(function () {
	const DOCTYPES = ["Lead", "Customer", "Opportunity"];
	const API = "alantech_erp.sales.activity";
	const ICONS = { Call: "📞", Meeting: "👥", Task: "☑", Note: "📝", Email: "✉", Comment: "💬" };
	const fmt_dt = "YYYY-MM-DD HH:mm:ss";
	const esc = (v) => frappe.utils.escape_html(v || "");

	function record_label(frm) {
		return frm.doc.lead_name || frm.doc.company_name || frm.doc.customer_name || frm.doc.title || frm.doc.name;
	}

	function default_owner(frm) {
		return frm.doc.lead_owner || frm.doc.account_manager || frm.doc.opportunity_owner || frappe.session.user;
	}

	// ------------------------------------------------------------------ new activity dialog
	alantech.activity.new = function (frm, type, defaults = {}) {
		const start = moment().add(1, "hour").startOf("hour");
		const who = record_label(frm);
		const subjects = {
			Call: __("Call with {0}", [who]),
			Meeting: __("Meeting with {0}", [who]),
			Task: __("Task for {0}", [who]),
			Note: __("Note on {0}", [who]),
		};
		const is = (types) => types.includes(type);
		const logged_now = type === "Note";
		const fields = [
			{ fieldname: "subject", fieldtype: "Data", label: __("Subject"), reqd: 1, default: subjects[type] },
			{
				fieldname: "status",
				fieldtype: "Select",
				label: __("Status"),
				options: is(["Call", "Meeting"]) ? "Open\nCompleted" : "Open",
				default: "Open",
				hidden: !is(["Call", "Meeting"]),
				description: is(["Call", "Meeting"]) ? __("Completed: already happened (log it); Open: scheduled") : "",
			},
			{
				fieldname: "activity_date",
				fieldtype: "Datetime",
				label: type === "Task" ? __("Start") : __("Date"),
				reqd: 1,
				default: logged_now ? frappe.datetime.now_datetime() : start.format(fmt_dt),
				hidden: logged_now,
			},
			{ fieldname: "ends_on", fieldtype: "Datetime", label: __("Ends On"), default: start.clone().add(30, "minutes").format(fmt_dt), hidden: !is(["Call", "Meeting"]) },
			{ fieldname: "activity_owner", fieldtype: "Link", options: "User", label: __("Owner"), reqd: 1, default: default_owner(frm) },
			{ fieldtype: "Column Break" },
			{
				fieldname: "follow_up_date",
				fieldtype: "Date",
				label: type === "Task" ? __("Due Date") : __("Follow-up Due Date"),
				reqd: type === "Task" ? 1 : 0,
				default: type === "Task" ? frappe.datetime.add_days(frappe.datetime.get_today(), 1) : null,
			},
			{ fieldname: "priority", fieldtype: "Select", label: __("Priority"), options: "Low\nMedium\nHigh", default: "Medium" },
			{
				fieldname: "contact_person",
				fieldtype: "Link",
				options: "Contact",
				label: __("Contact"),
				hidden: frm.doctype === "Lead",
				get_query: () => ({
					query: "frappe.contacts.doctype.contact.contact.contact_query",
					filters: { link_doctype: frm.doctype, link_name: frm.doc.name },
				}),
			},
			// call
			{ fieldtype: "Section Break", label: __("Call"), hidden: type !== "Call" },
			{ fieldname: "call_direction", fieldtype: "Select", label: __("Call Type"), options: "Outbound\nInbound", default: "Outbound" },
			{ fieldname: "call_result", fieldtype: "Select", label: __("Call Result"), options: "\nConnected\nNo Answer\nBusy\nLeft Voicemail\nWrong Number" },
			{ fieldtype: "Column Break" },
			{
				fieldname: "call_purpose",
				fieldtype: "Select",
				label: __("Call Purpose"),
				options: "\nProspecting\nRequirement Discussion\nFollow-up\nNegotiation\nDemo\nSupport\nOther",
			},
			{ fieldname: "phone", fieldtype: "Data", label: __("Phone"), default: frm.doc.mobile_no || frm.doc.phone || frm.doc.contact_mobile },
			// meeting
			{ fieldtype: "Section Break", label: __("Meeting"), hidden: type !== "Meeting" },
			{ fieldname: "meeting_mode", fieldtype: "Select", label: __("Meeting Mode"), options: "In Person\nOnline\nPhone", default: "In Person" },
			{ fieldname: "location", fieldtype: "Data", label: __("Location / Link") },
			{ fieldtype: "Column Break" },
			{ fieldname: "attendees", fieldtype: "MultiSelectPills", label: __("Our Attendees"), get_data: (txt) => frappe.db.get_link_options("User", txt) },
			// details
			{ fieldtype: "Section Break" },
			{ fieldname: "description", fieldtype: "Text Editor", label: type === "Note" ? __("Note") : __("Notes / Agenda"), reqd: type === "Note" ? 1 : 0 },
			{
				fieldname: "summary",
				fieldtype: "Small Text",
				label: __("Outcome / Summary"),
				hidden: !is(["Call", "Meeting"]),
				mandatory_depends_on: "eval:doc.status=='Completed'",
				depends_on: "eval:doc.status=='Completed'",
			},
		];
		const titles = { Call: __("Log Call"), Meeting: __("Schedule Meeting"), Task: __("Add Task"), Note: __("Add Note") };
		const d = new frappe.ui.Dialog({
			title: titles[type],
			size: "large",
			fields,
			primary_action_label: __("Save"),
			primary_action(values) {
				const doc = Object.assign({}, values, {
					doctype: "Sales Activity",
					activity_type: type,
					reference_doctype: frm.doctype,
					reference_name: frm.doc.name,
					attendees: (values.attendees || []).map((user) => ({ user })),
				});
				if (type === "Note") doc.status = "Completed";
				frappe.db.insert(doc).then((saved) => {
					d.hide();
					frappe.show_alert({ message: __("{0} saved", [__(type)]), indicator: "green" });
					alantech.activity.refresh(frm);
					frm.reload_docinfo && frm.reload_docinfo();
					return saved;
				});
			},
		});
		d.set_values(defaults);
		d.show();
		return d;
	};

	// ------------------------------------------------------------------ complete / follow up
	alantech.activity.complete = function (activity, after) {
		const needs_summary = ["Call", "Meeting"].includes(activity.activity_type);
		const d = new frappe.ui.Dialog({
			title: __("Complete {0}: {1}", [__(activity.activity_type), activity.subject]),
			fields: [
				{ fieldname: "summary", fieldtype: "Small Text", label: __("Outcome / Summary"), reqd: needs_summary ? 1 : 0, default: activity.summary },
				{ fieldtype: "Section Break", label: __("Next Follow-up (optional)") },
				{ fieldname: "follow_up_date", fieldtype: "Date", label: __("Follow-up Due Date") },
				{ fieldname: "follow_up_subject", fieldtype: "Data", label: __("Follow-up Subject"), depends_on: "follow_up_date" },
			],
			primary_action_label: __("Complete"),
			primary_action(values) {
				frappe.call({ method: `${API}.complete_activity`, args: Object.assign({ name: activity.name }, values), freeze: true }).then(() => {
					d.hide();
					frappe.show_alert({ message: __("Completed"), indicator: "green" });
					after && after();
				});
			},
		});
		d.show();
	};

	alantech.activity.follow_up = function (activity, after) {
		const d = new frappe.ui.Dialog({
			title: __("Follow-up of {0}", [activity.subject]),
			fields: [
				{ fieldname: "activity_type", fieldtype: "Select", label: __("Activity Type"), options: "Task\nCall\nMeeting", default: "Task", reqd: 1 },
				{ fieldname: "follow_up_date", fieldtype: "Date", label: __("Due Date"), reqd: 1, default: frappe.datetime.add_days(frappe.datetime.get_today(), 2) },
				{ fieldname: "subject", fieldtype: "Data", label: __("Subject"), default: __("Follow up: {0}", [activity.subject]) },
			],
			primary_action_label: __("Create"),
			primary_action(values) {
				frappe
					.call({ method: `${API}.make_follow_up`, args: Object.assign({ source_name: activity.name }, values), freeze: true })
					.then(({ message }) => {
						d.hide();
						frappe.show_alert({ message: __("Follow-up {0} created", [message]), indicator: "green" });
						after && after(message);
					});
			},
		});
		d.show();
	};

	// ------------------------------------------------------------------ panel on Lead / Customer / Deal
	alantech.activity.refresh = function (frm) {
		if (frm.is_new()) return;
		frappe.call({ method: `${API}.get_activity_summary`, args: { doctype: frm.doctype, name: frm.doc.name } }).then(({ message: s }) => {
			if (!s || frm.docname !== frm.doc.name) return;
			render_panel(frm, s);
		});
	};

	function render_panel(frm, s) {
		const today = frappe.datetime.get_today();
		const row = (a, pending) => {
			const due = pending ? a.due : null;
			const cls = pending ? (a.overdue ? "text-danger" : due === today ? "text-warning" : "text-muted") : "text-muted";
			const when = pending
				? (a.overdue ? __("Overdue") + " · " : "") + frappe.datetime.str_to_user(due)
				: frappe.datetime.comment_when(a.activity_date);
			const action =
				pending && a.status === "Open" && ["Call", "Meeting", "Task"].includes(a.activity_type)
					? `<a class="alt-act-complete small" data-name="${esc(a.name)}">${__("Complete")}</a>`
					: pending
						? `<a class="alt-act-followup small" data-name="${esc(a.name)}">${__("Follow up")}</a>`
						: "";
			const other = a.reference_doctype !== frm.doctype ? ` <span class="badge badge-light">${__("from Lead")}</span>` : "";
			return `<div class="alt-act-row" style="display:flex;gap:8px;align-items:baseline;padding:4px 0;border-bottom:1px solid var(--border-color)">
				<span>${ICONS[a.activity_type] || "•"}</span>
				<div style="flex:1;min-width:0">
					<a href="/app/sales-activity/${encodeURIComponent(a.name)}">${esc(a.subject)}</a>${other}
					<div class="small text-muted">${__(a.activity_type)} · ${esc(frappe.user.full_name(a.activity_owner))}${a.summary && !pending ? " · " + esc(a.summary).slice(0, 120) : ""
				}</div>
				</div>
				<span class="small ${cls}" style="white-space:nowrap">${when}</span>
				<span style="white-space:nowrap">${action}</span>
			</div>`;
		};
		const counts = ["Call", "Meeting", "Task", "Note", "Email", "Comment"]
			.filter((t) => s.counts[t])
			.map((t) => `${ICONS[t]} ${s.counts[t]} ${__(t + "s")}`)
			.join(" &nbsp; ");
		const head = `<div class="small text-muted" style="margin-bottom:6px">${counts || __("No activities yet.")}${s.last_contact ? " &nbsp;·&nbsp; " + __("Last activity {0}", [frappe.datetime.comment_when(s.last_contact)]) : ""
			}</div>`;
		const pending = s.pending.length
			? `<div class="small" style="font-weight:600;margin-top:4px">${__("Pending ({0}, {1} overdue)", [s.pending_count, s.overdue_count])}</div>` +
			s.pending.map((a) => row(a, true)).join("")
			: "";
		const recent = s.recent.length
			? `<div class="small" style="font-weight:600;margin-top:10px">${__("Latest")}</div>` + s.recent.map((a) => row(a, false)).join("")
			: "";
		const all = `<div style="margin-top:8px"><a class="alt-act-all small">${__("View all activities")}</a></div>`;
		const html = `<div class="alt-activities">${head}${pending}${recent}${all}</div>`;

		$(frm.dashboard.wrapper).find(".alt-activities").closest(".form-dashboard-section").remove();
		frm.dashboard.add_section(html, __("Activities"));
		const $w = $(frm.dashboard.wrapper);
		$w.find(".alt-act-complete").on("click", function () {
			const a = s.pending.find((x) => x.name === $(this).data("name"));
			alantech.activity.complete(a, () => alantech.activity.refresh(frm));
		});
		$w.find(".alt-act-followup").on("click", function () {
			const a = s.pending.find((x) => x.name === $(this).data("name"));
			alantech.activity.follow_up(a, () => alantech.activity.refresh(frm));
		});
		$w.find(".alt-act-all").on("click", () => {
			frappe.route_options = { reference_doctype: frm.doctype, reference_name: frm.doc.name };
			frappe.set_route("List", "Sales Activity");
		});
		if (s.overdue_count) {
			frm.dashboard.set_headline(__("{0} overdue follow-up(s) on this record.", [s.overdue_count]), "red");
		}
	}

	function add_buttons(frm) {
		if (frm.is_new() || !frappe.model.can_create("Sales Activity")) return;
		const group = __("Activity");
		frm.add_custom_button(__("Log Call"), () => alantech.activity.new(frm, "Call"), group);
		frm.add_custom_button(__("Schedule Meeting"), () => alantech.activity.new(frm, "Meeting"), group);
		frm.add_custom_button(__("Add Task"), () => alantech.activity.new(frm, "Task"), group);
		frm.add_custom_button(__("Add Note"), () => alantech.activity.new(frm, "Note"), group);
		frm.add_custom_button(__("Send Email"), () => new frappe.views.CommunicationComposer({ frm, doc: frm.doc }), group);
	}

	DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				add_buttons(frm);
				alantech.activity.refresh(frm);
			},
		});
	});

	// Core "New Task" dialog (Lead > Activities): its required Description field has no label and core lists
	// it twice, so saving it empty showed "Missing Values Required" with two empty bullets. For that dialog
	// only: label the unlabeled required fields when the dialog opens, and list each missing field once.
	const dialog_get_values = frappe.ui.Dialog.prototype.get_values;
	const core_msgprint = frappe.msgprint;
	let checking_task = false;
	const unique_items = (html) => {
		const seen = new Set();
		return html.replace(/<li>([^<]*)/g, (m, t) => (seen.has(t) ? "" : (seen.add(t), m)));
	};
	frappe.msgprint = function (msg, ...rest) {
		if (checking_task) {
			if (typeof msg === "string") msg = unique_items(msg);
			else if (msg && typeof msg.message === "string") msg = Object.assign({}, msg, { message: unique_items(msg.message) });
		}
		return core_msgprint.call(this, msg, ...rest);
	};
	const is_task_dialog = (d) => !!(d.fields_dict?.interaction_type && d.fields_dict?.description);
	const label_required = (d) =>
		(d.fields_list || []).forEach((f) => {
			if (!f.df.reqd) return;
			if (!f.df.label) f.df.label = __(frappe.unscrub(f.df.fieldname));
			// a field made without a label has an empty <label> with no text span: add the span
			const $label = f.$wrapper && f.$wrapper.find("label.control-label").first();
			if ($label && $label.length && !$label.find(".label-area").length) {
				$label.html(`<span class="label-area">${frappe.utils.escape_html(f.df.label)}</span>`);
				f.label_span = $label.find(".label-area")[0];
			}
			f.refresh_label && f.refresh_label();
			f.toggle_label && f.toggle_label(true);
		});
	const dialog_show = frappe.ui.Dialog.prototype.show;
	frappe.ui.Dialog.prototype.show = function (...args) {
		const r = dialog_show.apply(this, args);
		if (is_task_dialog(this)) {
			label_required(this);
			setTimeout(() => label_required(this), 0);
			this.$wrapper.one("shown.bs.modal", () => label_required(this));
		}
		return r;
	};
	frappe.ui.Dialog.prototype.get_values = function (...args) {
		if (!is_task_dialog(this)) return dialog_get_values.apply(this, args);
		label_required(this);
		checking_task = true;
		try {
			return dialog_get_values.apply(this, args);
		} finally {
			checking_task = false;
		}
	};
})();
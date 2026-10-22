// Copyright (c) 2026, JincyTricta and contributors
// For license information, please see license.txt

(() => {
	const MONTHS = [
		"January", "February", "March", "April", "May", "June",
		"July", "August", "September", "October", "November", "December",
	];
	const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
	const this_year = today.getFullYear();
	const years = [];
	for (let y = this_year; y >= this_year - 4; y--) years.push(String(y));

	const LOG_STATUS_COLOURS = {
		Draft: "gray",
		"Pending Approval": "orange",
		Approved: "blue",
		Rejected: "red",
		Processed: "green",
	};
	const ATTENDANCE_COLOURS = { Present: "green", "Half Day": "orange", Absent: "red", "On Leave": "blue" };

	const API = "alantech_erp.alantech.doctype.session_log.approval";
	const OPEN_STATUSES = ["Draft", "Pending Approval", "Approved"];

	function checked_rows() {
		const dt = frappe.query_report.datatable;
		if (!dt) return [];
		return dt.rowmanager.getCheckedRows().map((i) => frappe.query_report.data[i]).filter(Boolean);
	}

	function open_names(rows) {
		return rows.filter((r) => OPEN_STATUSES.includes(r.status)).map((r) => r.name);
	}

	function approve(names) {
		if (!names.length) {
			frappe.msgprint(__("No Draft, Pending or Approved logs to approve."));
			return;
		}
		frappe.confirm(__("Approve {0} log(s) and create their Attendance and Overtime?", [names.length]), () =>
			frappe.xcall(`${API}.approve_logs`, { names }).then((count) =>
				frappe.show_alert({
					message: __("Approving {0} log(s) in the background. The report refreshes when done.", [count]),
					indicator: "blue",
				})
			)
		);
	}

	function add_review_actions(report) {
		report.page.add_inner_button(__("Approve Selected"), () => {
			const rows = checked_rows();
			if (!rows.length) return frappe.msgprint(__("Tick the logs to approve first."));
			approve(open_names(rows));
		}, __("Review"));

		report.page.add_inner_button(__("Approve All"), () => {
			approve(open_names(frappe.query_report.data || []));
		}, __("Review"));

		report.page.add_inner_button(__("Reject"), () => {
			const names = open_names(checked_rows());
			if (!names.length) return frappe.msgprint(__("Tick the Draft, Pending or Approved logs to reject first."));
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Remark"), reqd: 1 },
				(v) =>
					frappe.xcall(`${API}.reject_logs`, { names, reason: v.reason }).then((count) => {
						frappe.show_alert({ message: __("{0} log(s) rejected", [count]), indicator: "red" });
						report.refresh();
					}),
				__("Reject {0} log(s)", [names.length]),
				__("Reject")
			);
		}, __("Review"));

		// background job finished
		frappe.realtime.off("session_log_approval_done");
		frappe.realtime.on("session_log_approval_done", (r) => {
			frappe.show_alert({
				message: __("Approval done: {0} processed, {1} failed, {2} skipped", [r.processed, r.failed, r.skipped]),
				indicator: r.failed ? "orange" : "green",
			});
			if (frappe.query_report && frappe.query_report.report_name === "Attendance Log Review") {
				frappe.query_report.refresh();
			}
		});
	}

	frappe.query_reports["Attendance Log Review"] = {
		filters: [
			{
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				reqd: 1,
				default: frappe.defaults.get_user_default("Company"),
			},
			{
				fieldname: "month",
				label: __("Month"),
				fieldtype: "Select",
				options: MONTHS,
				reqd: 1,
				default: MONTHS[today.getMonth()],
			},
			{
				fieldname: "year",
				label: __("Year"),
				fieldtype: "Select",
				options: years,
				reqd: 1,
				default: String(this_year),
			},
			{
				fieldname: "employee",
				label: __("Employee"),
				fieldtype: "Link",
				options: "Employee",
				get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
			},
			{
				fieldname: "department",
				label: __("Department"),
				fieldtype: "Link",
				options: "Department",
				get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
			},
			{
				fieldname: "project",
				label: __("Project / Site"),
				fieldtype: "Link",
				options: "Project",
			},
			{
				fieldname: "status",
				label: __("Status"),
				fieldtype: "Select",
				options: ["", "Draft", "Pending Approval", "Approved", "Rejected", "Processed"],
			},
			{
				fieldname: "show_flagged_only",
				label: __("Show Flagged Only"),
				fieldtype: "Check",
			},
		],

		// checkbox column for Approve Selected / Reject
		get_datatable_options(options) {
			return Object.assign(options, { checkboxColumn: true });
		},

		onload(report) {
			frappe
				.xcall("alantech_erp.alantech.doctype.session_log_settings.session_log_settings.get_session_log_settings")
				.then((settings) => {
					const is_approver =
						frappe.user.has_role(settings.approver_role) || frappe.session.user === "Administrator";
					if (is_approver) add_review_actions(report);
				});
		},

		formatter(value, row, column, data, default_formatter) {
			value = default_formatter(value, row, column, data);
			if (!data) return value;

			if (column.fieldname === "status" && data.status) {
				const colour = LOG_STATUS_COLOURS[data.status] || "gray";
				return `<span class="indicator-pill ${colour}">${__(data.status)}</span>`;
			}
			const off_day =
				["Weekly Off", "Holiday"].includes(data.day_type) &&
				!data.first_in &&
				data.attendance_status !== "On Leave";
			if (column.fieldname === "attendance_status" && off_day) {
				return `<span class="indicator-pill gray">${__("Off")}</span>`;
			}
			if (column.fieldname === "attendance_status" && data.attendance_status) {
				const colour = ATTENDANCE_COLOURS[data.attendance_status] || "gray";
				return `<span class="indicator-pill ${colour}">${__(data.attendance_status)}</span>`;
			}
			if (column.fieldname === "day_type" && data.day_type && data.day_type !== "Working Day") {
				return `<span class="text-info">${value}</span>`;
			}
			return value;
		},
	};
})();

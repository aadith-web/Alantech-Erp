// Check-in / check-out reminder popups (HR-F02). Server side: alantech_erp.api.checkin_reminder.
// One server call (get_reminder) says which popup is due now:
//   checkin  - no punch yet today
//   reentry  - checked out before the shift ends
//   checkout - the shift is over and the employee is still checked in
// Every popup comes back on every page, after every refresh, until the punch is applied.
// "Later" (or X / Esc) only hides it for REMIND_MS; a refresh shows it again straight away.
// Only ONE popup is ever open: checks are debounced into a single run and a popup of the same
// kind is never opened twice.
(() => {
  if (window.__alt_checkin_reminder) return; // script loaded twice: bind only once
  window.__alt_checkin_reminder = true;

  const API = "alantech_erp.api.checkin_reminder.";
  const TITLE = "Check-in Reminder";
  const REMIND_MS = 5 * 60 * 1000; // how long "Later" hides a popup (until a refresh)

  let active_dialog = null;
  let active_kind = null;
  let running = false;
  let timer = null;
  let realtime_bound = false;
  const hidden_until = {}; // per kind: set by Later, cleared by a refresh (page reload)

  function dialog_open() {
    return !!(active_dialog && active_dialog.display);
  }

  // Whatever opened it (this script, a stale cached copy, a realtime event), keep only the newest
  // "Check-in Reminder" dialog open.
  function dedupe() {
    const same = (frappe.ui.open_dialogs || []).filter(
      (d) => d.display && d.$wrapper && d.$wrapper.find(".modal-title").first().text().trim() === __(TITLE)
    );
    same.slice(0, -1).forEach((d) => {
      d.onhide = null;
      d.hide();
    });
  }

  function show_dialog({ kind, message, label, action, later = true }) {
    console.debug("[checkin-reminder] show", kind, new Error().stack.split("\n").slice(2, 5).join(" | "));
    if (dialog_open() && active_kind === kind) return; // never two popups of the same kind

    if (dialog_open()) {
      active_dialog.onhide = null; // replaced by another kind: not a dismissal
      active_dialog.hide();
    }

    const dlg = new frappe.ui.Dialog({
      title: __(TITLE),
      primary_action_label: label,
      primary_action: () => action(dlg),
      ...(later && {
        secondary_action_label: __("Later"),
        secondary_action: () => dlg.hide(),
      }),
    });
    dlg.$body.html(`<p>${frappe.utils.escape_html(message)}</p>`);
    dlg.onhide = () => (hidden_until[kind] = Date.now() + REMIND_MS); // Later, X or Esc
    dlg.show();
    active_dialog = dlg;
    active_kind = kind;
  }

  function punch(employee, log_type, done_message, dlg) {
    dlg.disable_primary_action();
    frappe.call({
      method: "frappe.client.insert",
      args: {
        doc: {
          doctype: "Employee Checkin",
          employee,
          log_type,
          time: frappe.datetime.now_datetime(),
        },
      },
      callback() {
        dlg.hide();
        frappe.show_alert({ message: done_message, indicator: "green" });
      },
      error: () => dlg.enable_primary_action(),
    });
  }

  function correction_dialog(kind, date) {
    show_dialog({
      kind,
      message: __(
        "Your check-out for {0} is missing. Please request correction of the previous day's check-out before checking in.",
        [date]
      ),
      label: __("OK"),
      action: (dlg) => dlg.hide(),
      later: false,
    });
  }

  function show_checkin(d) {
    if (d.missing_checkout) return correction_dialog("checkin", d.missing_checkout);
    show_dialog({
      kind: "checkin",
      message: __("Hi {0}, you haven't marked your check-in for today ({1}).", [d.employee_name, d.date]),
      label: __("Check In"),
      action: (dlg) => punch(d.employee, "IN", __("Checked in"), dlg),
    });
  }

  function show_reentry(d) {
    hidden_until.reentry = 0; // pushed by the server: show it now
    show_dialog({
      kind: "reentry",
      message: __(
        "Hi {0}, you checked out before your shift ends at {1}. Do you want to check in again?",
        [d.employee_name, d.shift_end]
      ),
      label: __("Check In"),
      action: (dlg) => punch(d.employee, "IN", __("Checked in"), dlg),
    });
  }

  function show_checkout(d) {
    if (d.missing_checkout) return correction_dialog("checkout", d.missing_checkout);
    show_dialog({
      kind: "checkout",
      message: __("Hi {0}, your shift ended at {1} and you haven't checked out. Do you want to check out now?", [
        d.employee_name,
        d.shift_end,
      ]),
      label: __("Check Out"),
      action: (dlg) => punch(d.employee, "OUT", __("Checked out"), dlg),
    });
  }

  const SHOW = { checkin: show_checkin, reentry: show_reentry, checkout: show_checkout };

  async function run_checks() {
    if (running || !frappe.session || frappe.session.user === "Guest") return;
    if (dialog_open()) return;
    running = true;
    try {
      const d = (await frappe.call({ method: API + "get_reminder" })).message || {};
      if (!d.show_popup || !SHOW[d.kind]) return;
      if (Date.now() < (hidden_until[d.kind] || 0)) return; // dismissed with Later
      SHOW[d.kind](d);
    } finally {
      running = false;
    }
  }

  // app_ready, route changes and the timer all land here: one check per burst, never two
  function schedule(delay = 600) {
    clearTimeout(timer);
    timer = setTimeout(run_checks, delay);
  }

  function bind_realtime() {
    // the socket does not exist when this file loads: bind once the desk is ready
    if (realtime_bound || !frappe.realtime.socket) return;
    frappe.realtime.on("checkin_reentry_prompt", show_reentry);
    realtime_bound = true;
  }

  $(document).on("shown.bs.modal", dedupe);
  $(document).on("app_ready", () => {
    bind_realtime();
    schedule(800);
    setInterval(() => schedule(0), REMIND_MS);
  });
  frappe.router.on("change", () => {
    bind_realtime();
    schedule(600);
  });
})();
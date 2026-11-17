// Check-in reminder popups (HR-F02). Server side: alantech_erp.api.checkin_reminder.
//  1. Daily reminder: once per browser session per day, only on home / workspace screens.
//  2. Re-entry prompt: after an in-shift check-out it shows on every page and after every refresh
//     until the employee checks in again or the shift ends. Pushed at once by a realtime event,
//     and re-checked from the server on load, on page changes and every REMIND_MS.
//     "Later" only hides it for REMIND_MS (a refresh shows it again straight away).
// Only ONE popup is ever open: checks are debounced into a single run and a popup of the same
// kind is never opened twice.
(() => {
  if (window.__alt_checkin_reminder) return; // script loaded twice: bind only once
  window.__alt_checkin_reminder = true;

  const API = "alantech_erp.api.checkin_reminder.";
  const HOME_ROUTES = ["", "desktop", "home", "workspace", "workspaces"];
  const REMIND_MS = 5 * 60 * 1000; // how long "Later" hides the re-entry popup (until a refresh)

  let active_dialog = null;
  let active_kind = null;
  let running = false;
  let timer = null;
  let reentry_hidden_until = 0;
  let realtime_bound = false;

  function is_home() {
    const route = frappe.get_route() || [];
    return HOME_ROUTES.includes(String(route[0] || "").toLowerCase());
  }

  function storage_key() {
    return `alt_checkin_reminder:${frappe.session.user}:${frappe.datetime.get_today()}`;
  }

  function dialog_open() {
    return !!(active_dialog && active_dialog.display);
  }

  const TITLE = "Check-in Reminder";

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

  function show_dialog({ kind, message, label, action, later = true, on_hide }) {
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
    if (on_hide) dlg.onhide = on_hide;
    dlg.show();
    active_dialog = dlg;
    active_kind = kind;
  }

  function check_in(employee, dlg) {
    dlg.disable_primary_action();
    frappe.call({
      method: "frappe.client.insert",
      args: {
        doc: {
          doctype: "Employee Checkin",
          employee,
          log_type: "IN",
          time: frappe.datetime.now_datetime(),
        },
      },
      callback() {
        dlg.hide();
        frappe.show_alert({ message: __("Checked in"), indicator: "green" });
      },
      error: () => dlg.enable_primary_action(),
    });
  }

  function show_daily_reminder(d) {
    if (d.missing_checkout) {
      show_dialog({
        kind: "daily",
        message: __(
          "Your check-out for {0} is missing. Please request correction of the previous day's check-out before checking in.",
          [d.missing_checkout]
        ),
        label: __("OK"),
        action: (dlg) => dlg.hide(),
        later: false,
      });
      return;
    }
    show_dialog({
      kind: "daily",
      message: __("Hi {0}, you haven't marked your check-in for today ({1}).", [d.employee_name, d.date]),
      label: __("Check In"),
      action: (dlg) => check_in(d.employee, dlg),
    });
  }

  function show_reentry_prompt(d) {
    reentry_hidden_until = 0;
    show_dialog({
      kind: "reentry",
      message: __(
        "Hi {0}, you checked out before your shift ends at {1}. Do you want to check in again?",
        [d.employee_name, d.shift_end]
      ),
      label: __("Check In"),
      action: (dlg) => check_in(d.employee, dlg),
      on_hide: () => (reentry_hidden_until = Date.now() + REMIND_MS), // Later, X or Esc
    });
  }

  async function run_checks() {
    if (running || !frappe.session || frappe.session.user === "Guest") return;
    if (dialog_open()) return;
    running = true;
    try {
      // 1. re-entry (any page): checked out inside the shift
      if (Date.now() < reentry_hidden_until) return; // dismissed with Later
      const re = (await frappe.call({ method: API + "get_reentry_status" })).message || {};
      if (re.show_popup) return show_reentry_prompt(re);

      // 2. daily reminder (home only, once per session per day)
      if (!is_home() || sessionStorage.getItem(storage_key())) return;
      const daily = (await frappe.call({ method: API + "get_checkin_status" })).message || {};
      if (!daily.show_popup) return;
      sessionStorage.setItem(storage_key(), "1");
      show_daily_reminder(daily);
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
    frappe.realtime.on("checkin_reentry_prompt", show_reentry_prompt);
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
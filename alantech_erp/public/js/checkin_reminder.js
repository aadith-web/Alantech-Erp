// Home page check-in reminder (HR-F02). Server side: alantech_erp.api.checkin_reminder.
// Shown once per browser session per day, only on the home / workspace screens.
(() => {
  const API = "alantech_erp.api.checkin_reminder.";
  const HOME = ["", "desktop", "home", "workspace", "workspaces"];

  function is_home() {
    const route = frappe.get_route() || [];
    return HOME.includes(String(route[0] || "").toLowerCase());
  }

  function storage_key() {
    return `alt_checkin_reminder:${frappe.session.user}:${frappe.datetime.get_today()}`;
  }

  function show(d) {
    const esc = frappe.utils.escape_html;
    let message, dlg;
    if (d.missing_checkout) {
      message = __("Your check-out for {0} is missing. Please request correction of the previous day's check-out before checking in.", [d.missing_checkout]);
      dlg = new frappe.ui.Dialog({ title: __("Check-in Reminder"), primary_action_label: __("OK"), primary_action: () => dlg.hide() });
    } else {
      message = __("Hi {0}, you haven't marked your check-in for today ({1}). Please create your Employee Checkin now.", [d.employee_name, d.date]);
      dlg = new frappe.ui.Dialog({
        title: __("Check-in Reminder"),
        primary_action_label: __("Check In Now"),
        primary_action() {
          dlg.hide();
          frappe.new_doc("Employee Checkin", { employee: d.employee });
        },
        secondary_action_label: __("Later"),
        secondary_action: () => dlg.hide(),
      });
    }
    dlg.$body.html(`<p>${esc(message)}</p>`);
    dlg.show();
  }

  let checking = false;
  function check() {
    if (checking || !frappe.session || frappe.session.user === "Guest" || !is_home()) return;
    if (sessionStorage.getItem(storage_key())) return;
    checking = true;
    frappe.call({
      method: API + "get_checkin_status",
      callback(r) {
        const d = r.message || {};
        if (!d.show_popup) return;
        sessionStorage.setItem(storage_key(), "1");
        show(d);
      },
      always: () => (checking = false),
    });
  }

  $(document).on("app_ready", () => setTimeout(check, 500));
  frappe.router.on("change", () => setTimeout(check, 300));
})();
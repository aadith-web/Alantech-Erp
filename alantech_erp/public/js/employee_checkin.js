// Employee Checkin: a new form opened by the logged-in employee is filled in automatically (HR-F02).
frappe.ui.form.on("Employee Checkin", {
  async onload(frm) {
    if (!frm.is_new() || frm.__alt_prefilled) return;
    frm.__alt_prefilled = true;

    const { message: emp } = await frappe.call({
      method: "alantech_erp.api.checkin_reminder.get_current_employee",
    });
    if (!emp) return;

    if (!frm.doc.employee) await frm.set_value("employee", emp.employee);
    if (frm.doc.employee !== emp.employee) return;
    if (!frm.doc.employee_name) await frm.set_value("employee_name", emp.employee_name);
    if (!frm.doc.time) await frm.set_value("time", frappe.datetime.now_datetime());
    if (!frm.doc.log_type) await frm.set_value("log_type", emp.log_type);
  },
});
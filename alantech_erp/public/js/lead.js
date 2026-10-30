frappe.ui.form.on("Lead", {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.add_custom_button(__("Call"), () => open_activity_dialog(frm, "Call"), __("Activity"));
    frm.add_custom_button(__("Meeting"), () => open_activity_dialog(frm, "Meeting"), __("Activity"));
  },
});

function open_activity_dialog(frm, category) {
  const fmt = "YYYY-MM-DD HH:mm:ss";
  const start = moment().add(1, "hour").startOf("hour");
  const end = start.clone().add(30, "minutes");
  const who = frm.doc.lead_name || frm.doc.company_name || frm.doc.name;

  const d = new frappe.ui.Dialog({
    title: __("New {0}", [__(category)]),
    fields: [
      { fieldname: "subject", fieldtype: "Small Text", label: __("Subject"), reqd: 1, default: `${category} with ${who}` },
      { fieldname: "status", fieldtype: "Select", label: __("Status"), options: "Open\nCompleted\nClosed\nCancelled", default: "Open", reqd: 1 },
      { fieldtype: "Column Break" },
      { fieldname: "starts_on", fieldtype: "Datetime", label: __("Starts on"), reqd: 1, default: start.format(fmt) },
      { fieldname: "ends_on", fieldtype: "Datetime", label: __("Ends on"), default: end.format(fmt) },
      { fieldname: "attachment", fieldtype: "Attach", label: __("Attachment") },
    ],
    primary_action_label: __("Save"),
    primary_action(values) {
      if (values.ends_on && moment(values.ends_on).isBefore(values.starts_on)) {
        frappe.msgprint(__("Ends on cannot be before Starts on"));
        return;
      }

      const finish = () => {
        d.hide();
        frappe.show_alert({ message: __("{0} created", [__(category)]), indicator: "green" });
        frm.reload_doc();
      };

      frappe.call({
        method: "frappe.client.insert",
        args: {
          doc: {
            doctype: "Event",
            subject: values.subject,
            event_category: category,
            event_type: "Public",
            status: values.status,
            starts_on: values.starts_on,
            ends_on: values.ends_on,
            reference_doctype: "Lead",
            reference_docname: frm.doc.name,
            event_participants: [
              {
                reference_doctype: "Lead",
                reference_docname: frm.doc.name,
                email: frm.doc.email_id,
              },
            ],
          },
        },
        freeze: true,
        callback(r) {
          if (!r.message) return;
          const event_name = r.message.name;

          if (!values.attachment) return finish();

          // attach the uploaded file to the new Event
          frappe.call({
            method: "frappe.client.get_value",
            args: { doctype: "File", filters: { file_url: values.attachment }, fieldname: "name" },
            callback(g) {
              const file_name = g.message && g.message.name;
              if (!file_name) return finish();
              frappe.call({
                method: "frappe.client.set_value",
                args: {
                  doctype: "File",
                  name: file_name,
                  fieldname: { attached_to_doctype: "Event", attached_to_name: event_name },
                },
                callback: finish,
                error: finish,
              });
            },
            error: finish,
          });
        },
      });
    },
  });

  d.show();
}
(function () {
    const s = frappe.listview_settings["Employee Checkin"] || (frappe.listview_settings["Employee Checkin"] = {});
    const orig_onload = s.onload;
    s.onload = function (listview) {
        if (orig_onload) orig_onload.call(this, listview);
        const is_hr = frappe.user.has_role("HR Manager") || frappe.user.has_role("HR User");
        if (!is_hr) {
            listview.page.remove_inner_button(__("Add Checkin for Another Employee"));
        }
    };
})();

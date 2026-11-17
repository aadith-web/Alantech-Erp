// Bell notifications are marked read when viewed (ClickUp 14yr2e57yr3).
//
// Frappe v16's bell has no per-notification "read": an item stays unread until "Mark all as read",
// and the count only goes up (new notification) or to 0 (mark all). Here:
//   - clicking a notification in the bell marks it read (setup/notifications.mark_read);
//   - opening a document the bell lists as unread marks its notifications read as well (opened
//     from the bell, from an email link or from the list: the user has seen it);
//   - every bell count (sidebar, dock) is set to the real number of unread notifications, also in
//     the user's other open tabs (realtime "alt_notification_read").
// Frappe itself is not changed.

(() => {
	const METHOD = "alantech_erp.setup.notifications.mark_read";
	const READ_EVENT = "alt_notification_read";

	// Frappe's bell (frappe.ui.Notifications, made by the sidebar)
	const bell_view = () => frappe.app?.sidebar?.notifications?.tabs?.notifications;

	function set_count(count) {
		const view = bell_view();
		if (view?.update_count_badge) {
			view.update_count_badge(count);
		} else {
			const $count = $(".notification-count");
			if (count > 0) $count.text(count > 99 ? "99+" : count).removeClass("hidden");
			else $count.addClass("hidden");
		}
	}

	function show_as_read(names) {
		const view = bell_view();
		(names || []).forEach((name) => {
			$(`.notification-item[data-name="${CSS.escape(name)}"]`).removeClass("unread");
			const item = (view?.dropdown_items || []).find((log) => log && log.name === name);
			if (item) item.read = 1;
		});
	}

	function mark_read(args) {
		return frappe
			.xcall(METHOD, args)
			.then((r) => {
				if (!r) return;
				show_as_read(r.names);
				set_count(r.unread);
			})
			.catch(() => {}); // never in the user's way; the next page load shows the server count
	}

	// 1. click on a notification in the bell (Frappe also follows the link to the document)
	$(document).on("click", ".notification-item[data-name]", function () {
		const name = $(this).attr("data-name");
		if (!name || !$(this).hasClass("unread")) return;
		$(this).removeClass("unread");
		mark_read({ names: [name] });
	});

	// 2. a document the bell lists as unread is opened
	function unread_for(doctype, docname) {
		return (bell_view()?.dropdown_items || []).some(
			(log) => log && !log.read && log.document_type === doctype && log.document_name === docname
		);
	}

	$(document).on("form-refresh", (e, frm) => {
		if (!frm || frm.is_new?.() || !frm.doc?.name) return;
		if (frm.doctype === "Notification Log") {
			if (frm.doc.for_user === frappe.session.user && !frm.doc.read) mark_read({ names: [frm.doc.name] });
			return;
		}
		if (unread_for(frm.doctype, frm.doc.name)) {
			mark_read({ document_type: frm.doctype, document_name: frm.doc.name });
		}
	});

	// 3. the user's other tabs
	$(document).on("app_ready", () => {
		frappe.realtime.on(READ_EVENT, (data) => {
			if (!data) return;
			show_as_read(data.names);
			set_count(data.unread);
		});
	});
})();

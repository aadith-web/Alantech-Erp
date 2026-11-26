// Employee profile (HRMS employee_profile.vue, an island with an open shadow root): a "Company
// Policy" item after "Assets" in the sidebar. Its panel lists the policies that apply to the employee
// shown (title and code), and a click opens the policy's attached file. HRMS is not changed: the item
// is added to the rendered sidebar, and the panel is shown in the content column in place of the
// section Vue renders. Server: alantech/doctype/company_policy/company_policy.get_applicable_policies.
(() => {
	if (window.__alt_company_policy) return;
	window.__alt_company_policy = true;

	const METHOD = "alantech_erp.alantech.doctype.company_policy.company_policy.get_applicable_policies";
	const LABEL = "Company Policy";
	const ICON = "lucide-file-text";
	const ACTIVE = "bg-surface-gray-2";
	const IDLE = "bg-transparent";
	const CSS = `.alt-cp-panel { display: none; } .alt-cp-on > .alt-cp-panel { display: block; } .alt-cp-on > :not(.alt-cp-panel) { display: none !important; }`;

	// A policy counts as new for this many days after its effective date, until the employee opens it
	const NEW_DAYS = 30;
	const SEEN_KEY = "alt_cp_seen";
	const OPEN_KEY = "alt_cp_open";

	let panel_open = false;
	let open_column = null; // the content column the panel is in
	let open_previous = []; // the sidebar buttons that were active before the panel opened
	let cache = { employee: null, rows: null };
	let loading = false;
	let loading_since = 0;

	function policy_key(employee, row) {
		return [employee, row.policy_code || row.policy_title, row.version || "", row.effective_date || ""].join("|");
	}

	function seen_set() {
		try {
			return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"));
		} catch (e) {
			return new Set();
		}
	}

	function mark_seen(employee, row) {
		const seen = seen_set();
		seen.add(policy_key(employee, row));
		try {
			localStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
		} catch (e) { }
	}

	function new_count(rows, employee) {
		const cutoff = Date.now() - NEW_DAYS * 24 * 60 * 60 * 1000;
		const seen = seen_set();
		return rows.filter(
			(row) =>
				row.effective_date &&
				new Date(row.effective_date).getTime() >= cutoff &&
				!seen.has(policy_key(employee, row)),
		).length;
	}

	// Count badge after the label, like the Documents and Assets counts
	function set_count(button, n) {
		const current = button.querySelector(":scope > [data-alt-cp-count]");
		if (!n) {
			current?.remove();
			return;
		}
		if (current && current.textContent === String(n)) return;
		current?.remove();
		const badge = text("span", "text-p-sm text-ink-gray-5 shrink-0", String(n));
		badge.setAttribute("data-alt-cp-count", "");
		badge.title = __("New policies");
		button.append(badge);
	}

	function employee_from_route() {
		const path = window.location.pathname;
		if (!path.includes("/hr-setup/employee/")) return null;
		const name = path.split("/hr-setup/employee/")[1].split("/")[0];
		return name ? decodeURIComponent(name) : null;
	}

	// The profile renders inside the island's shadow root; find the one that has the sidebar's Assets item
	function find_profile_root() {
		for (const host of document.querySelectorAll(".frappe-island")) {
			const root = host.shadowRoot;
			if (root && desktop_nav(root)) return root;
		}
		return null;
	}

	function desktop_nav(root) {
		return [...root.querySelectorAll("aside div.hidden")].find((div) =>
			[...div.querySelectorAll(":scope > button")].some((b) => b.textContent.trim().startsWith("Assets")),
		);
	}

	function assets_button(nav) {
		return [...nav.querySelectorAll(":scope > button")].find((b) => b.textContent.trim().startsWith("Assets"));
	}

	function column_of(nav) {
		return assets_button(nav).closest("aside").nextElementSibling;
	}

	function add_style(root) {
		if (root.querySelector("style[data-alt-cp]")) return;
		const style = document.createElement("style");
		style.setAttribute("data-alt-cp", "");
		style.textContent = CSS;
		root.appendChild(style);
	}

	function set_button_state(button, active) {
		if (!button) return;
		button.classList.toggle(ACTIVE, active);
		button.classList.toggle(IDLE, !active);
	}

	function show_panel(nav, employee, scroll) {
		const column = column_of(nav);
		if (!column) return;
		let panel = column.querySelector(":scope > .alt-cp-panel");
		if (!panel) {
			panel = document.createElement("div");
			panel.className = "alt-cp-panel px-4 sm:px-0 space-y-3";
			panel.style.scrollMarginTop = "170px"; // keeps the heading below the sticky header and tabs
			column.prepend(panel);
		}
		if (!panel_open) {
			open_previous = [...nav.querySelectorAll(":scope > button")].filter((b) => b.classList.contains(ACTIVE));
		}
		open_column = column;
		column.classList.add("alt-cp-on");
		panel_open = true;
		try { sessionStorage.setItem(OPEN_KEY, employee); } catch (e) { }
		[...nav.querySelectorAll(":scope > button")].forEach((b) => set_button_state(b, false));
		set_button_state(nav.querySelector(":scope > button[data-alt-cp]"), true);
		render(panel, employee);
		if (scroll) panel.scrollIntoView({ behavior: "smooth", block: "start" });
	}

	// Leave the panel and show Vue's content again. `restore` puts back the sidebar button that was
	// active before the panel opened; it is used when the user clicks outside the sidebar, since Vue
	// has not changed its section then. A sidebar click leaves the choice to Vue.
	function hide_panel(restore) {
		if (!panel_open) return;
		panel_open = false;
		try { sessionStorage.removeItem(OPEN_KEY); } catch (e) { }
		open_column?.classList.remove("alt-cp-on");
		const root = find_profile_root();
		const nav = root && desktop_nav(root);
		if (nav) {
			set_button_state(nav.querySelector(":scope > button[data-alt-cp]"), false);
			if (restore) {
				[...nav.querySelectorAll(":scope > button")].forEach((b) => set_button_state(b, false));
				open_previous.forEach((b) => b.isConnected && set_button_state(b, true));
			}
		}
		open_column = null;
	}

	function text(tag, cls, value) {
		const el = document.createElement(tag);
		if (cls) el.className = cls;
		el.textContent = value ?? "";
		return el;
	}

	function render(panel, employee) {
		panel.replaceChildren(text("p", "text-p-base text-ink-gray-5", __("Loading policies…")));
		const load = cache.employee === employee && cache.rows
			? Promise.resolve(cache.rows)
			: frappe.xcall(METHOD, { employee }).then((rows) => {
				cache = { employee, rows };
				return rows;
			});
		load.then((rows) => {
			if (!panel.isConnected || !panel.parentElement?.classList.contains("alt-cp-on")) return;
			const fresh = new_count(rows, employee);
			const head = text(
				"div",
				"text-p-lg font-semibold text-ink-gray-8",
				`${LABEL} (${rows.length})${fresh ? ` · ${fresh} ${__("new")}` : ""}`,
			);
			if (!rows.length) {
				panel.replaceChildren(head, text("p", "text-p-base text-ink-gray-5", __("No company policy applies to this employee.")));
				return;
			}
			const list = document.createElement("div");
			list.className = "flex flex-col gap-2";
			for (const row of rows) list.appendChild(policy_row(row, employee));
			panel.replaceChildren(head, list);
		}).catch(() => {
			panel.replaceChildren(text("p", "text-p-base text-ink-red-3", __("Could not load company policies.")));
		});
	}

	function policy_row(row, employee) {
		const item = document.createElement("button");
		item.type = "button";
		item.className = "w-full text-left flex items-center justify-between gap-3 rounded-6 border px-4 py-3 bg-surface-white hover:bg-surface-gray-2";
		const info = document.createElement("div");
		info.className = "min-w-0";
		info.append(
			text("div", "text-p-base font-medium text-ink-gray-8 truncate", row.policy_title),
			text("div", "text-p-sm text-ink-gray-5 truncate", [row.policy_code, row.version && `v${row.version}`].filter(Boolean).join(" · ")),
		);
		item.append(info, text("span", "text-p-sm text-ink-gray-5 shrink-0", __("Open")));
		item.addEventListener("click", () => {
			if (row.policy_file) {
				mark_seen(employee, row);
				window.open(row.policy_file, "_blank", "noopener");
				// refresh the "N new" text; the sidebar badge updates on the next ensure() tick
				const panel = open_column?.querySelector(":scope > .alt-cp-panel");
				if (panel) render(panel, employee);
			} else frappe.show_alert({ message: __("This policy has no file attached."), indicator: "orange" });
		});
		return item;
	}

	// Clicks outside the profile island (the form's own tabs such as Profile or Personal, the page
	// header) show a different page section, so the panel closes and the sidebar goes back to that choice
	document.addEventListener("click", (event) => {
		if (!panel_open) return;
		const host = document.querySelector(".frappe-island");
		if (host && event.composedPath().includes(host)) return;
		hide_panel(true);
	}, true);

	// Vue re-renders the sidebar when sections change, which drops our item: add it back with a
	// fresh click handler, and keep its look in step with the panel
	function ensure() {
		const employee = employee_from_route();
		if (!employee) {
			try { sessionStorage.removeItem(OPEN_KEY); } catch (e) { }
			return;
		}
		const root = find_profile_root();
		if (!root) return;
		const nav = desktop_nav(root);
		const assets = assets_button(nav);
		add_style(root);
		// Vue replaced the content column (the panel went with it): the panel is no longer showing
		if (panel_open && !open_column?.isConnected) panel_open = false;

		// Clicks on any Vue sidebar button, anywhere in the shadow root, leave the panel for that section.
		// Listening on the root (which Vue keeps) survives the sidebar being re-rendered.
		if (!root.__alt_cp_listening) {
			root.__alt_cp_listening = true;
			root.addEventListener("click", (event) => {
				const button = event.target.closest?.("button");
				if (!button) return;
				// any sidebar item (direct child of the nav): bring the content to the top.
				// Our own button scrolls through show_panel, so skip it here.
				const side = button.closest("aside");
				if (side && !button.hasAttribute("data-alt-cp") && side.nextElementSibling) {
					const column = side.nextElementSibling;
					setTimeout(() => scroll_to(column), 150);
				}
				if (button.hasAttribute("data-alt-cp") || button.closest(".alt-cp-panel") || !panel_open) return;
				hide_panel(false);
				// Vue restyles a button only when its section changes, so the Assets button is restyled
				// by hand when it is clicked while its own panel is showing
				if (button.textContent.trim().startsWith("Assets")) set_button_state(button, true);
			}, true);
		}

		let our_button = nav.querySelector(":scope > button[data-alt-cp]");
		if (!our_button) {
			our_button = document.createElement("button");
			our_button.type = "button";
			our_button.setAttribute("data-alt-cp", "");
			our_button.className = assets.className;
			const icon = document.createElement("span");
			icon.className = `${ICON} size-4`;
			our_button.append(icon, text("span", "truncate leading-tighter", LABEL));
			assets.after(our_button);
			our_button.addEventListener("click", () => {
				const current = employee_from_route();
				const live_root = find_profile_root();
				const live_nav = live_root && desktop_nav(live_root);
				if (current && live_nav) show_panel(live_nav, current, true);
			});
		}

		// coming back from the policy tab: Vue re-rendered and closed the panel, so show the list again
		let want = null;
		try { want = sessionStorage.getItem(OPEN_KEY); } catch (e) { }
		if (want === employee && !panel_open) show_panel(nav, employee);

		set_button_state(our_button, panel_open);

		// the new-policy count comes from the same list the panel shows
		if (cache.employee === employee && cache.rows) {
			set_count(our_button, new_count(cache.rows, employee));
		} else if (!loading || Date.now() - loading_since > 10000) {
			// a request that never answers is retried after 10 seconds
			loading = true;
			loading_since = Date.now();
			frappe.xcall(METHOD, { employee })
				.then((rows) => {
					cache = { employee, rows };
					set_count(our_button, new_count(rows, employee));
				})
				.catch(() => { })
				.finally(() => (loading = false));
		}
	}

	// The island mounts asynchronously and re-renders its sidebar, so keep checking
	setInterval(() => {
		try {
			ensure();
		} catch (e) {
			console.warn("Company Policy profile item:", e);
		}
	}, 500);
})();
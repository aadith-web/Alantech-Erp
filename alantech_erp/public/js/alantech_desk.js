// Alantech ERP — apps screen (/desk) welcome banner for Frappe v16.
// Adds a greeting hero above the app icons. Pure decoration: if the v16 markup
// changes and .desktop-container is not found, nothing happens.
(() => {
	const HERO_CLASS = "al-desk-hero";

	function greeting() {
		const h = new Date().getHours();
		if (h < 12) return __("Good morning");
		if (h < 17) return __("Good afternoon");
		return __("Good evening");
	}

	function first_name() {
		const info = frappe.user_info ? frappe.user_info(frappe.session.user) : null;
		const full = (info && info.fullname) || frappe.boot?.user?.first_name || frappe.session.user;
		return String(full).split(" ")[0];
	}

	function build_hero() {
		const date = new Date().toLocaleDateString(frappe.boot?.lang || undefined, {
			weekday: "long",
			day: "numeric",
			month: "long",
			year: "numeric",
		});
		const esc = frappe.utils.escape_html;
		return $(`
			<section class="${HERO_CLASS}" aria-label="${esc(__("Welcome"))}">
				<div class="al-desk-hero__text">
					<p class="al-desk-hero__date">${esc(date)}</p>
					<h1 class="al-desk-hero__title">${esc(greeting())}, ${esc(first_name())}</h1>
					<p class="al-desk-hero__subtitle">${esc(__("Pick an app to get started."))}</p>
				</div>
			</section>
		`);
	}

	function ensure_hero() {
		const $container = $(".desktop-wrapper .desktop-container");
		if (!$container.length) return;
		const $existing = $container.children("." + HERO_CLASS);
		if ($existing.length) {
			// refresh greeting/date when the page is shown again later in the day
			$existing.replaceWith(build_hero());
		} else {
			$container.prepend(build_hero());
		}
		$container.addClass("al-desk-launcher");
	}

	// The desktop page re-renders its icons on every show; re-attach after it does.
	let observer = null;
	function watch() {
		const el = document.querySelector(".desktop-wrapper .desktop-container");
		if (!el || el.dataset.alWatched) return;
		el.dataset.alWatched = "1";
		observer = new MutationObserver(() => {
			if (!el.querySelector(":scope > ." + HERO_CLASS)) ensure_hero();
		});
		observer.observe(el, { childList: true });
	}

	function on_route() {
		if (frappe.get_route_str?.() !== "desktop" && !document.querySelector(".desktop-wrapper")) return;
		// wait a tick for the page body to be rendered
		setTimeout(() => {
			ensure_hero();
			watch();
		}, 0);
	}

	$(document).on("page-change", on_route);
	frappe.router?.on?.("change", on_route);
	$(on_route);
})();

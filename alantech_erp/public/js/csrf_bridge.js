// frappe-ui components used inside the desk read the CSRF token from `window.csrf_token`
// (frappe/ui FileUpload/useFileUpload.ts), which only the standalone pages (/hrms, Studio, Roster)
// set. The desk sets `frappe.csrf_token` only (www/desk.html), so an upload from a desk island, such
// as "Change cover" on the HRMS Employee Profile, was sent without the token and refused by Frappe
// as "Invalid Request". This makes `window.csrf_token` read the desk's token, also after Frappe
// refreshes it. Remove once Frappe sets it on the desk itself.
(() => {
	if (typeof window === "undefined" || !window.frappe) return;
	const own = Object.getOwnPropertyDescriptor(window, "csrf_token");
	if (own && own.value && own.value !== "{{ csrf_token }}") return; // a page that sets its own
	Object.defineProperty(window, "csrf_token", {
		configurable: true,
		get: () => frappe.csrf_token,
	});
})();

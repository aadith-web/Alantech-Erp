// Phone fields (e.g. Employee Mobile): the country code picker would not open on a saved record.
// Frappe's ControlPhone.make_input is async and runs again when the field refreshes before it has
// finished, which builds a second picker and binds the flag's click twice: one click opens the
// picker and the second closes it again. Build the input once.
(() => {
	const ControlPhone = frappe.ui.form.ControlPhone;
	if (!ControlPhone) return;
	const make_input = ControlPhone.prototype.make_input;
	ControlPhone.prototype.make_input = function () {
		if (!this.alt_making_input) this.alt_making_input = make_input.call(this);
		return this.alt_making_input;
	};
})();

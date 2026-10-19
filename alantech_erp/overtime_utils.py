import frappe
from frappe.utils import flt, get_last_day

def get_overtime_settings():
    settings = frappe.get_cached_doc("Overtime Settings")

    if not settings.working_hours_per_day:
        frappe.throw("Working Hours Per Day must be greater than 0 in Overtime Settings")

    return {
        "enable_multiple_ot": settings.enable_multiple_ot,
        "rules": {r.ot_type: r for r in settings.overtime_type_rules},
        "base_component_method": settings.base_component_method,
        "applicable_components": [
            c.salary_component for c in settings.applicable_overtime_component
        ],
        "working_days_base": settings.working_days_base,
        "working_hours_per_day": settings.working_hours_per_day,
    }


def get_overtime_hours_by_type(employee, start_date, end_date):
    rows = frappe.get_all(
        "Overtime Log",
        filters={
            "employee": employee,
            "docstatus": 1,
            "overtime_date": ["between", [start_date, end_date]],
        },
        fields=["ot_type", {"SUM": "overtime_hours", "as": "hours"}],
        group_by="ot_type",
    )
    return {r.ot_type: r.hours or 0 for r in rows}

def get_working_days(settings, slip):
    base = settings["working_days_base"]
    if base == "Year Average":
        return 365 / 12
    if base == "Month Days":
        return get_last_day(slip.start_date).day
    if base == "Fixed 30":
        return 30
    frappe.throw(f"Unsupported Working Days Base: {base}")


def get_base_amount(slip, rule, settings, ot_components):
    """Full monthly base, never the amount prorated by payment days."""
    if rule.component_method == "Component Wise":
        applicable = set(settings["applicable_components"])
        return sum(
            flt(d.default_amount or d.amount)
            for d in slip.earnings
            if d.salary_component in applicable
        )

    if rule.component_method == "Full Salary":
        return sum(
            flt(d.default_amount or d.amount)
            for d in slip.earnings
            if d.salary_component not in ot_components
            and not d.statistical_component
            and not d.do_not_include_in_total
        )

    frappe.throw(f"Unsupported Component Method: {rule.component_method}")


def calculate_overtime_amounts(slip):
    """Returns {salary_component: amount}, with rules sharing a component merged."""
    settings = get_overtime_settings()
    hours_by_type = get_overtime_hours_by_type(
        slip.employee, slip.start_date, slip.end_date
    )
    if not hours_by_type:
        return {}

    rules = settings["rules"]
    ot_components = {r.salary_component for r in rules.values()}
    working_days = get_working_days(settings, slip)
    hours_per_day = settings["working_hours_per_day"]

    amounts = {}
    for ot_type, hours in hours_by_type.items():
        rule = rules.get(ot_type)
        if not rule or flt(hours) <= 0:
            continue

        if rule.calculation_method == "Fixed Rate":
            hourly_rate = flt(rule.fixed_hourly_rate)
        else:
            base = get_base_amount(slip, rule, settings, ot_components)
            hourly_rate = base / (working_days * hours_per_day)

        multiplier = flt(rule.rate_multiplier) or 1
        amount = flt(hours) * hourly_rate * multiplier

        amounts[rule.salary_component] = amounts.get(rule.salary_component, 0) + amount

    return {c: flt(a, 2) for c, a in amounts.items()}

def add_overtime_components(doc, method=None):
    """Salary Slip validate hook."""
    if doc.docstatus == 2 or not (doc.employee and doc.start_date and doc.end_date):
        return

    settings = get_overtime_settings()  # errors if Working Hours Per Day is 0
    rules = settings["rules"]
    ot_components = {r.salary_component for r in rules.values()}

    # OT components must not be part of the Salary Structure
    if doc.salary_structure:
        structure = frappe.get_cached_doc("Salary Structure", doc.salary_structure)
        clash = ot_components & {d.salary_component for d in structure.earnings}
        if clash:
            frappe.throw(
                frappe._("OT components {0} must not be part of Salary Structure {1}").format(
                    ", ".join(sorted(clash)), doc.salary_structure
                )
            )

    # 1. Remove OT rows added earlier, so saving again doesn't duplicate them
    removed = [d for d in doc.earnings if d.salary_component in ot_components]
    for d in removed:
        doc.remove(d)
    for i, d in enumerate(doc.earnings, 1):
        d.idx = i

    # No OT hours, or no rule matches: leave the slip unchanged
    hours_by_type = get_overtime_hours_by_type(doc.employee, doc.start_date, doc.end_date)
    matched = {t: h for t, h in hours_by_type.items() if t in rules and flt(h) > 0}
    if not matched:
        if removed:
            doc.calculate_net_pay()
        return

    # Errors: working days is zero, or an applicable component is missing
    if not get_working_days(settings, doc):
        frappe.throw(frappe._("Working Days must be greater than 0"))

    if any(rules[t].component_method == "Component Wise" for t in matched):
        present = {d.salary_component for d in doc.earnings}
        missing = [c for c in settings["applicable_components"] if c not in present]
        if missing or not settings["applicable_components"]:
            frappe.throw(
                frappe._("Applicable Overtime Component missing from Salary Slip: {0}").format(
                    ", ".join(missing) or frappe._("none configured")
                )
            )

    # 2. Add one earning row per salary component
    amounts = calculate_overtime_amounts(doc)
    info = {}
    for ot_type, hours in matched.items():
        comp = rules[ot_type].salary_component
        row = info.setdefault(comp, {"hours": 0, "types": []})
        row["hours"] += flt(hours)
        row["types"].append(ot_type)

    for comp, amount in amounts.items():
        sc = frappe.get_cached_doc("Salary Component", comp)
        doc.append("earnings", {
            "salary_component": comp,
            "abbr": sc.get("salary_component_abbr"),
            "amount": amount,
            "default_amount": amount,
            "depends_on_payment_days": 0,
            "custom_overtime_hours": info[comp]["hours"],
            "custom_ot_type": ", ".join(info[comp]["types"]),
            "statistical_component": sc.get("statistical_component"),
            "do_not_include_in_total": sc.get("do_not_include_in_total"),
            "is_tax_applicable": sc.get("is_tax_applicable"),
        })

    # 3. Recalculate gross pay, tax and net pay
    doc.calculate_net_pay()
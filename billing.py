"""billing.py - ALL pricing and billing rules live here.

Change a number in SETTINGS or DAMAGE_CATEGORIES and the whole program follows.
Nothing else in the project hard-codes a loan period, margin or penalty.

BILLING CONVENTION (documented on purpose - read this!)
  * Due date          = issue date + loan_period_days.
  * Chargeable days   = days from issue date to return date, counting BOTH days.
                        Issued 1 Jan, returned 6 Jan  ->  6 chargeable days.
                        Returned the same day         ->  1 chargeable day.
  * Late days         = max(0, return date - due date) in calendar days.

NOTE ON "MARGIN": the margin is a MARKUP added to the base rate to get the
price we charge. It is NOT profit. Real net profit = money actually collected
minus the library's costs (book purchases, repairs, staff, rent ...).
"""

from datetime import timedelta
from decimal import Decimal

from helpers import round_money, to_decimal

SETTINGS = {
    "loan_period_days": 7,                      # days a book may be kept
    "default_margin_percent": Decimal("10"),    # markup added to the base rate
    "late_fee_percent": Decimal("10"),          # % of daily rate charged per late day
}

# Damage policy: percent of the book's purchase cost (used as replacement cost).
# book_status / condition = what we record on the book after it is returned.
DAMAGE_CATEGORIES = [
    {"key": "none", "label": "No damage", "percent": Decimal("0"),
     "book_status": "Available", "condition": "Good"},
    {"key": "minor", "label": "Minor tears or markings", "percent": Decimal("10"),
     "book_status": "Available", "condition": "Minor damage"},
    {"key": "major", "label": "Major tearing or damaged binding", "percent": Decimal("30"),
     "book_status": "Damaged", "condition": "Major damage"},
    {"key": "lost", "label": "Lost or unusable book", "percent": Decimal("100"),
     "book_status": "Lost", "condition": "Lost"},
]


def get_damage_category(key):
    for category in DAMAGE_CATEGORIES:
        if category["key"] == key:
            return category
    raise ValueError(f"Unknown damage category '{key}'.")


def calculate_final_rate(base_rate, margin_percent):
    """Final daily rate = base rate x (1 + margin / 100), rounded to 2 places."""
    base = to_decimal(base_rate, "Base rate")
    margin = to_decimal(margin_percent, "Margin percent")
    return round_money(base * (1 + margin / 100))


def calculate_due_date(issue_date):
    return issue_date + timedelta(days=SETTINGS["loan_period_days"])


def calculate_chargeable_days(issue_date, return_date):
    if return_date < issue_date:
        raise ValueError("Return date cannot be before the issue date.")
    return (return_date - issue_date).days + 1


def calculate_late_days(due_date, return_date):
    return max(0, (return_date - due_date).days)


def calculate_late_penalty(daily_rate, late_days):
    """Late penalty = late days x daily rate x late fee %."""
    return round_money(late_days * to_decimal(daily_rate) * SETTINGS["late_fee_percent"] / 100)


def calculate_bill(daily_rate, issue_date, due_date, return_date, purchase_cost, damage_key):
    """Work out the complete bill for one return. Returns a dictionary."""
    rate = round_money(to_decimal(daily_rate, "Daily rate"))
    cost = round_money(to_decimal(purchase_cost, "Purchase cost"))
    category = get_damage_category(damage_key)

    chargeable_days = calculate_chargeable_days(issue_date, return_date)
    late_days = calculate_late_days(due_date, return_date)

    rental_charge = round_money(rate * chargeable_days)
    late_penalty = calculate_late_penalty(rate, late_days)
    damage_penalty = round_money(cost * category["percent"] / 100)
    total = rental_charge + late_penalty + damage_penalty

    return {
        "daily_rate": rate,
        "purchase_cost": cost,
        "chargeable_days": chargeable_days,
        "late_days": late_days,
        "rental_charge": rental_charge,
        "late_penalty": late_penalty,
        "damage_key": category["key"],
        "damage_label": category["label"],
        "damage_percent": category["percent"],
        "damage_penalty": damage_penalty,
        "total": total,
    }


def estimate_late_penalty(daily_rate, due_date, as_of_date):
    """For books still out: (late days so far, penalty so far)."""
    late_days = calculate_late_days(due_date, as_of_date)
    return late_days, calculate_late_penalty(daily_rate, late_days)


def policy_lines():
    """Plain-English rental policy printed on every receipt."""
    late = SETTINGS["late_fee_percent"]
    return [
        f"Loan period: {SETTINGS['loan_period_days']} days from the issue date.",
        "Rental is charged per day, counting the issue day and the return day.",
        f"Late return: {late}% of the daily rate is charged for each day after the due date.",
        "Damage / loss: " + "; ".join(
            f"{c['label']} {c['percent']}%" for c in DAMAGE_CATEGORIES if c["percent"] > 0
        ) + " of the book's purchase cost.",
    ]

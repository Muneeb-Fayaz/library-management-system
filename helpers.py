"""helpers.py - small reusable tools: input validation, money, dates, tables.

Every function here does one small job. The rest of the project uses them so
that "what counts as a valid price / date / ID" is decided in ONE place.

Validation functions raise ValueError with a friendly message. The menu
(main.py) catches that error and shows the message to the librarian.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CURRENCY = "₹"
TWO_PLACES = Decimal("0.01")
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")
ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")
CONTACT_PATTERN = re.compile(r"^\+?\d{7,15}$")


# ---------------------------------------------------------------- money
def to_decimal(value, field="Value"):
    """Convert text to Decimal. Always goes through str() so floats never sneak in."""
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{field} must be a number (got '{value}').")
    if not number.is_finite():
        raise ValueError(f"{field} must be a normal number (got '{value}').")
    return number


def round_money(amount):
    """Round to 2 decimal places (0.005 rounds UP, like normal shop billing)."""
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def parse_money(text, field="Amount", allow_zero=True):
    """Parse a price or amount. Rejects negatives (and zero if allow_zero=False)."""
    cleaned = str(text).replace(CURRENCY, "").replace(",", "").strip()
    number = to_decimal(cleaned, field)
    if number < 0:
        raise ValueError(f"{field} cannot be negative.")
    if number == 0 and not allow_zero:
        raise ValueError(f"{field} must be greater than zero.")
    return round_money(number)


def parse_percent(text, field="Percentage"):
    """Parse a percentage between 0 and 100."""
    number = to_decimal(str(text).replace("%", ""), field)
    if number < 0 or number > 100:
        raise ValueError(f"{field} must be between 0 and 100.")
    return round_money(number)


def money_or_zero(text):
    """Read a money value from a CSV cell. Blank means 0 (e.g. loan not billed yet)."""
    if str(text).strip() == "":
        return Decimal("0.00")
    return round_money(to_decimal(text, "Stored amount"))


def format_money(amount):
    """Show money for people: ₹1,234.50"""
    return f"{CURRENCY}{round_money(amount):,.2f}"


# ---------------------------------------------------------------- numbers / text
def parse_positive_int(text, field="Number", maximum=None):
    try:
        number = int(str(text).strip())
    except ValueError:
        raise ValueError(f"{field} must be a whole number (got '{text}').")
    if number < 1:
        raise ValueError(f"{field} must be at least 1.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} cannot be more than {maximum}.")
    return number


def parse_text(text, field="Value", max_len=100):
    """Trim spaces and make sure the text is not empty or absurdly long."""
    value = " ".join(str(text).split())
    if not value:
        raise ValueError(f"{field} cannot be empty.")
    if len(value) > max_len:
        raise ValueError(f"{field} is too long (maximum {max_len} characters).")
    return value


def parse_id(text, field="ID"):
    """IDs are stored in capitals: letters, digits, '-' and '_' only."""
    value = str(text).strip().upper()
    if not ID_PATTERN.match(value):
        raise ValueError(
            f"{field} may contain only letters, digits, '-' and '_' (max 20 characters)."
        )
    return value


def parse_contact(text):
    """Contact number: 7-15 digits, optional leading +. Spaces and dashes are ignored."""
    cleaned = str(text).replace(" ", "").replace("-", "")
    if not CONTACT_PATTERN.match(cleaned):
        raise ValueError("Contact number must be 7 to 15 digits (a leading + is allowed).")
    return cleaned


# ---------------------------------------------------------------- dates
def today():
    return date.today()


def parse_date(text, field="Date"):
    """Accepts 2026-03-15, 15-03-2026 or 15/03/2026. Returns a date object."""
    raw = str(text).strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"{field} '{raw}' is not a valid date. Use YYYY-MM-DD (e.g. 2026-03-15).")


def as_date(value, field="Date"):
    """Accept either a date object or text; always return a date object."""
    if isinstance(value, date):
        return value
    return parse_date(value, field)


def check_not_future(value, field="Date"):
    if value > today():
        raise ValueError(f"{field} cannot be in the future.")
    return value


# ---------------------------------------------------------------- printing
def print_table(headers, rows):
    """Print a simple aligned text table. rows is a list of lists."""
    if not rows:
        print("  (no records)")
        return
    text_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in text_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in text_rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))

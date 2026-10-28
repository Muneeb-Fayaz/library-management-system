"""library.py - the business logic: books, students, loans and payments.

This file never prints menus or asks questions (that is main.py's job). It
receives values, checks them, changes the CSV data and returns results or raises
ValueError with a clear message.

KEY IDEA: "issued" is never typed in by hand. A copy is issued if it has a loan
with status 'Active'. So the counts can never disagree with the loan records.
"""

import billing
import storage
from helpers import (
    as_date, check_not_future, money_or_zero, parse_contact, parse_id, parse_money,
    parse_percent, parse_positive_int, parse_text, round_money, today,
)
from storage import DataError

BOOK_STATUSES = ["Available", "Damaged", "Lost", "Under Repair"]
BOOK_CONDITIONS = ["New", "Good", "Fair", "Worn"]
PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Other"]

STATUS_COUNT_KEY = {
    "Available": "available", "Damaged": "damaged",
    "Lost": "lost", "Under Repair": "under_repair",
}

EDITABLE_TEXT = {"title": "Title", "author": "Author", "category": "Category",
                 "publisher": "Publisher"}


# ================================================================ small helpers
def _find(rows, key, value, label):
    """Find one row by ID (case-insensitive) or raise a friendly error."""
    wanted = str(value).strip().upper()
    for row in rows:
        if row[key].upper() == wanted:
            return row
    raise ValueError(f"{label} '{str(value).strip()}' was not found.")


def next_id(prefix, existing_ids, width=4):
    """B0001, B0002 ... : one more than the highest number already used."""
    highest = 0
    for value in existing_ids:
        number = value.upper()[len(prefix):]
        if value.upper().startswith(prefix) and number.isdigit():
            highest = max(highest, int(number))
    return f"{prefix}{highest + 1:0{width}d}"


def _money_text(amount):
    return str(round_money(amount))


def _active_book_ids(loans):
    return {loan["book_id"].upper() for loan in loans if loan["loan_status"] == "Active"}


def _same_title(first, second):
    return (first["title"].lower(), first["author"].lower()) == (
        second["title"].lower(), second["author"].lower())


# ================================================================ books
def add_books(details, copies=1, book_id=None):
    """Add one or more physical copies of a title. Returns the new book rows.

    details: dict with title, author, category, publisher, purchase_cost,
             base_daily_rate, and optionally margin_percent and condition.
    book_id: optional custom ID (only when adding exactly one copy).
    """
    copies = parse_positive_int(copies, "Number of copies", maximum=100)
    title = parse_text(details.get("title", ""), "Title")
    author = parse_text(details.get("author", ""), "Author")
    category = parse_text(details.get("category", ""), "Category")
    publisher = parse_text(details.get("publisher", ""), "Publisher")
    purchase_cost = parse_money(details.get("purchase_cost", ""), "Purchase cost")
    base_rate = parse_money(details.get("base_daily_rate", ""), "Base daily rate",
                            allow_zero=False)
    margin = parse_percent(
        details.get("margin_percent", billing.SETTINGS["default_margin_percent"]),
        "Margin percentage")
    condition = parse_text(details.get("condition", "Good"), "Condition")
    final_rate = billing.calculate_final_rate(base_rate, margin)

    if book_id is not None and copies != 1:
        raise ValueError("A custom book ID can only be used when adding one copy.")

    rows = storage.read_rows("books")
    used_ids = {row["book_id"].upper() for row in rows}
    new_rows = []
    for _ in range(copies):
        if book_id is None:
            new_id = next_id("B", used_ids)
        else:
            new_id = parse_id(book_id, "Book ID")
            if new_id in used_ids:
                raise ValueError(f"Book ID {new_id} already exists. Every copy needs its own ID.")
        used_ids.add(new_id)
        new_rows.append({
            "book_id": new_id, "title": title, "author": author, "category": category,
            "publisher": publisher, "purchase_cost": _money_text(purchase_cost),
            "base_daily_rate": _money_text(base_rate), "margin_percent": _money_text(margin),
            "daily_rate": _money_text(final_rate), "condition": condition,
            "status": "Available",
        })
    storage.write_rows("books", rows + new_rows)
    return new_rows


def list_books():
    """All copies, each with an extra 'state' = Issued (from loans) or its status."""
    books = storage.read_rows("books")
    active = _active_book_ids(storage.read_rows("loans"))
    result = []
    for book in books:
        item = dict(book)
        item["state"] = "Issued" if book["book_id"].upper() in active else book["status"]
        result.append(item)
    return result


def get_book(book_id):
    return _find(list_books(), "book_id", book_id, "Book")


def search_books(term):
    """Search by ID, title, author or category (partial, ignores capitals)."""
    word = parse_text(term, "Search text").lower()
    return [b for b in list_books()
            if word in b["book_id"].lower() or word in b["title"].lower()
            or word in b["author"].lower() or word in b["category"].lower()]


def available_copies():
    return [b for b in list_books() if b["state"] == "Available"]


def update_book_details(book_id, changes, all_copies=False):
    """Change title/author/category/publisher/purchase_cost/base_daily_rate/margin_percent.

    all_copies=True applies the change to every copy of the same title+author.
    Loans already issued keep their locked daily rate.
    """
    if not changes:
        raise ValueError("Nothing to update.")
    clean = {}
    for key, value in changes.items():
        if key in EDITABLE_TEXT:
            clean[key] = parse_text(value, EDITABLE_TEXT[key])
        elif key == "purchase_cost":
            clean[key] = _money_text(parse_money(value, "Purchase cost"))
        elif key == "base_daily_rate":
            clean[key] = _money_text(parse_money(value, "Base daily rate", allow_zero=False))
        elif key == "margin_percent":
            clean[key] = _money_text(parse_percent(value, "Margin percentage"))
        else:
            raise ValueError(f"'{key}' cannot be changed here.")

    rows = storage.read_rows("books")
    book = _find(rows, "book_id", book_id, "Book")
    targets = [r for r in rows if _same_title(r, book)] if all_copies else [book]
    for row in targets:
        row.update(clean)
        row["daily_rate"] = _money_text(
            billing.calculate_final_rate(row["base_daily_rate"], row["margin_percent"]))
    storage.write_rows("books", rows)
    return targets


def set_book_status(book_id, status, condition=None):
    """Mark a copy Available, Damaged, Lost or Under Repair."""
    wanted = str(status).strip().lower()
    match = [s for s in BOOK_STATUSES if s.lower() == wanted]
    if not match:
        raise ValueError(f"Status must be one of: {', '.join(BOOK_STATUSES)}.")
    rows = storage.read_rows("books")
    book = _find(rows, "book_id", book_id, "Book")
    if book["book_id"].upper() in _active_book_ids(storage.read_rows("loans")):
        raise ValueError(f"{book['book_id']} is currently issued. Return it before changing its status.")
    book["status"] = match[0]
    if condition:
        book["condition"] = parse_text(condition, "Condition")
    storage.write_rows("books", rows)
    return book


def inventory_counts():
    """Every number is CALCULATED from books.csv and loans.csv."""
    books = storage.read_rows("books")
    active = _active_book_ids(storage.read_rows("loans"))
    counts = {"titles": len({(b["title"].lower(), b["author"].lower()) for b in books}),
              "total": len(books), "available": 0, "issued": 0,
              "damaged": 0, "lost": 0, "under_repair": 0}
    for book in books:
        if book["book_id"].upper() in active:
            counts["issued"] += 1
        elif book["status"] in STATUS_COUNT_KEY:
            counts[STATUS_COUNT_KEY[book["status"]]] += 1
        else:
            raise DataError(f"books.csv: {book['book_id']} has an unknown status '{book['status']}'.")
    return counts


# ================================================================ students
def add_student(student_id, name, contact_number, registration_date=None):
    student_id = parse_id(student_id, "Student ID")
    name = parse_text(name, "Name")
    contact = parse_contact(contact_number)
    joined = check_not_future(as_date(registration_date or today(), "Registration date"),
                              "Registration date")
    rows = storage.read_rows("students")
    if any(r["student_id"].upper() == student_id for r in rows):
        raise ValueError(f"Student ID {student_id} is already registered.")
    row = {"student_id": student_id, "name": name, "contact_number": contact,
           "registration_date": joined.isoformat()}
    storage.write_rows("students", rows + [row])
    return row


def list_students():
    return storage.read_rows("students")


def get_student(student_id):
    return _find(storage.read_rows("students"), "student_id", student_id, "Student")


def search_students(term):
    word = parse_text(term, "Search text").lower()
    return [s for s in list_students()
            if word in s["student_id"].lower() or word in s["name"].lower()]


def student_active_loans(student_id):
    """List of (loan, book) for books this student currently holds."""
    student = get_student(student_id)
    books = storage.read_rows("books")
    result = []
    for loan in storage.read_rows("loans"):
        if loan["student_id"].upper() == student["student_id"].upper() \
                and loan["loan_status"] == "Active":
            result.append((loan, _find(books, "book_id", loan["book_id"], "Book")))
    return result


# ================================================================ loans
def get_loan(loan_id):
    return _find(storage.read_rows("loans"), "loan_id", loan_id, "Loan")


def issue_book(student_id, book_id, issue_date=None):
    """Issue one copy to one student. Returns (loan, book, student)."""
    student = get_student(student_id)
    books = storage.read_rows("books")
    book = _find(books, "book_id", book_id, "Book")
    loans = storage.read_rows("loans")

    if book["book_id"].upper() in _active_book_ids(loans):
        raise ValueError(f"Book {book['book_id']} is already issued to someone else.")
    if book["status"] != "Available":
        raise ValueError(f"Book {book['book_id']} is marked '{book['status']}' and cannot be issued.")

    issued_on = check_not_future(as_date(issue_date or today(), "Issue date"), "Issue date")
    loan = {
        "loan_id": next_id("L", [l["loan_id"] for l in loans]),
        "book_id": book["book_id"], "student_id": student["student_id"],
        "issue_date": issued_on.isoformat(),
        "due_date": billing.calculate_due_date(issued_on).isoformat(),
        "return_date": "",
        "daily_rate_at_issue": _money_text(money_or_zero(book["daily_rate"])),  # locked price
        "chargeable_days": "", "late_days": "", "rental_charge": "", "late_penalty": "",
        "damage_category": "", "damage_penalty": "", "total_amount_due": "",
        "loan_status": "Active",
    }
    storage.write_rows("loans", loans + [loan])
    return loan, book, student


def _prepare_return(identifier, return_date, damage_key):
    """Find the active loan and work out its bill WITHOUT saving anything."""
    ident = str(identifier).strip().upper()
    if not ident:
        raise ValueError("Enter a loan ID or a book ID.")
    loans = storage.read_rows("loans")
    books = storage.read_rows("books")

    by_loan = [l for l in loans if l["loan_id"].upper() == ident]
    by_book = [l for l in loans if l["book_id"].upper() == ident and l["loan_status"] == "Active"]
    if by_loan and by_loan[0]["loan_status"] != "Active":
        raise ValueError(f"Loan {ident} was already returned. A loan cannot be returned twice.")
    matches = by_loan or by_book
    if not matches:
        _find(books, "book_id", ident, "Loan or book")  # gives a "not found" error if unknown
        raise ValueError(f"Book {ident} is not currently issued.")
    if len(matches) > 1:
        raise DataError(f"loans.csv has more than one active loan for {ident}. Fix the file.")

    loan = matches[0]
    book = _find(books, "book_id", loan["book_id"], "Book")
    returned_on = check_not_future(as_date(return_date or today(), "Return date"), "Return date")
    bill = billing.calculate_bill(
        loan["daily_rate_at_issue"], as_date(loan["issue_date"]), as_date(loan["due_date"]),
        returned_on, book["purchase_cost"], damage_key)
    return loan, book, bill, returned_on, loans, books


def preview_return(identifier, return_date=None, damage_key="none"):
    """Show what the bill WOULD be. Nothing is saved. Returns (loan, book, bill)."""
    loan, book, bill, _, _, _ = _prepare_return(identifier, return_date, damage_key)
    return loan, book, bill


def return_book(identifier, return_date=None, damage_key="none"):
    """Close a loan, store the bill, update the book. Returns (loan, book, bill)."""
    loan, book, bill, returned_on, loans, books = _prepare_return(
        identifier, return_date, damage_key)
    category = billing.get_damage_category(damage_key)

    loan.update({
        "return_date": returned_on.isoformat(),
        "chargeable_days": str(bill["chargeable_days"]),
        "late_days": str(bill["late_days"]),
        "rental_charge": _money_text(bill["rental_charge"]),
        "late_penalty": _money_text(bill["late_penalty"]),
        "damage_category": bill["damage_key"],
        "damage_penalty": _money_text(bill["damage_penalty"]),
        "total_amount_due": _money_text(bill["total"]),
        "loan_status": "Returned",
    })
    book["status"] = category["book_status"]
    book["condition"] = category["condition"]

    # Loan first: if the program stops between the two saves, the loan is still
    # correctly closed (issued-ness is derived from loans) and only the book's
    # damage note is missing.
    storage.write_rows("loans", loans)
    storage.write_rows("books", books)
    return loan, book, bill


def overdue_loans(as_of=None):
    """Active loans past their due date, with the late penalty built up so far."""
    as_of = as_date(as_of or today(), "As-of date")
    books = storage.read_rows("books")
    students = storage.read_rows("students")
    result = []
    for loan in storage.read_rows("loans"):
        if loan["loan_status"] != "Active":
            continue
        late_days, penalty = billing.estimate_late_penalty(
            loan["daily_rate_at_issue"], as_date(loan["due_date"]), as_of)
        if late_days > 0:
            book = _find(books, "book_id", loan["book_id"], "Book")
            student = _find(students, "student_id", loan["student_id"], "Student")
            result.append({"loan": loan, "book": book, "student": student,
                           "late_days": late_days, "penalty": penalty})
    return result


# ================================================================ payments
def payments_for_loan(loan_id):
    wanted = str(loan_id).strip().upper()
    return [p for p in storage.read_rows("payments") if p["loan_id"].upper() == wanted]


def total_paid(loan_id):
    return round_money(sum((money_or_zero(p["amount"]) for p in payments_for_loan(loan_id)),
                           start=money_or_zero("")))


def outstanding_balance(loan_id):
    """Amount still owed on a returned (billed) loan = total billed - total paid."""
    loan = get_loan(loan_id)
    if loan["loan_status"] != "Returned":
        raise ValueError(f"Loan {loan['loan_id']} is still active, so it has no bill yet.")
    return round_money(money_or_zero(loan["total_amount_due"]) - total_paid(loan["loan_id"]))


def payment_status(total_due, paid):
    if total_due - paid <= 0:
        return "Paid"
    return "Unpaid" if paid == 0 else "Partial"


def record_payment(loan_id, amount, method, reference="", payment_date=None):
    """Save one payment (partial payments allowed). Returns the payment row."""
    loan = get_loan(loan_id)
    balance = outstanding_balance(loan["loan_id"])      # also checks the loan is billed
    amount = parse_money(amount, "Payment amount", allow_zero=False)
    if amount > balance:
        raise ValueError(
            f"Payment of {amount} is more than the outstanding balance of {balance}.")

    wanted = str(method).strip().lower()
    match = [m for m in PAYMENT_METHODS if m.lower() == wanted]
    if not match:
        raise ValueError(f"Payment method must be one of: {', '.join(PAYMENT_METHODS)}.")

    paid_on = check_not_future(as_date(payment_date or today(), "Payment date"), "Payment date")
    if paid_on < as_date(loan["return_date"]):
        raise ValueError("Payment date cannot be before the return (billing) date.")

    payments = storage.read_rows("payments")
    ids = {p["payment_id"].upper() for p in payments}
    new_id = next_id("P", ids)
    if new_id in ids:
        raise ValueError(f"Payment ID {new_id} already exists.")
    row = {"payment_id": new_id, "loan_id": loan["loan_id"], "payment_date": paid_on.isoformat(),
           "amount": _money_text(amount), "payment_method": match[0],
           "reference_number": " ".join(str(reference).split())}
    storage.write_rows("payments", payments + [row])
    return row

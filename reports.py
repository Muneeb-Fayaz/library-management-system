"""reports.py - read-only reports. Nothing here changes any CSV file.

Money rules used by every report (so nothing is double-counted):
  * BILLED     = total_amount_due of loans that have been RETURNED (each loan once).
  * COLLECTED  = sum of payments.csv (money actually received).
  * OUTSTANDING = billed - collected, worked out loan by loan.
Unpaid charges are never counted as income.

Reminder: margin is a pricing markup, NOT net profit. Net profit needs the
library's costs (purchases, repairs, salaries, rent), which this program does not track.
"""

from decimal import Decimal

import library
import storage
from helpers import (
    as_date, format_money, money_or_zero, print_table, round_money, today,
)

ZERO = Decimal("0.00")


# ================================================================ data functions
def financial_totals():
    """Return a dictionary of billed / collected / outstanding totals."""
    loans = storage.read_rows("loans")
    payments = storage.read_rows("payments")

    paid_by_loan = {}
    for payment in payments:
        key = payment["loan_id"].upper()
        paid_by_loan[key] = paid_by_loan.get(key, ZERO) + money_or_zero(payment["amount"])

    totals = {"rental": ZERO, "late": ZERO, "damage": ZERO, "billed": ZERO,
              "collected": ZERO, "outstanding": ZERO}
    for loan in loans:
        if loan["loan_status"] != "Returned":
            continue
        billed = money_or_zero(loan["total_amount_due"])
        paid = paid_by_loan.get(loan["loan_id"].upper(), ZERO)
        totals["rental"] += money_or_zero(loan["rental_charge"])
        totals["late"] += money_or_zero(loan["late_penalty"])
        totals["damage"] += money_or_zero(loan["damage_penalty"])
        totals["billed"] += billed
        totals["outstanding"] += max(billed - paid, ZERO)
    totals["collected"] = sum(paid_by_loan.values(), ZERO)
    return {key: round_money(value) for key, value in totals.items()}


def income_by_date():
    """Date-wise report: billed on the RETURN date, collected on the PAYMENT date."""
    days = {}
    for loan in storage.read_rows("loans"):
        if loan["loan_status"] == "Returned":
            day = days.setdefault(loan["return_date"], {"billed": ZERO, "collected": ZERO})
            day["billed"] += money_or_zero(loan["total_amount_due"])
    for payment in storage.read_rows("payments"):
        day = days.setdefault(payment["payment_date"], {"billed": ZERO, "collected": ZERO})
        day["collected"] += money_or_zero(payment["amount"])
    return dict(sorted(days.items()))


def outstanding_loans():
    """Returned loans that still owe money: list of (loan, balance)."""
    result = []
    for loan in storage.read_rows("loans"):
        if loan["loan_status"] == "Returned":
            balance = library.outstanding_balance(loan["loan_id"])
            if balance > 0:
                result.append((loan, balance))
    return result


def _loan_money(loan):
    """(billed, paid, balance) for any loan; active loans show 0 because not billed yet."""
    if loan["loan_status"] != "Returned":
        return ZERO, ZERO, ZERO
    billed = money_or_zero(loan["total_amount_due"])
    paid = library.total_paid(loan["loan_id"])
    return billed, paid, round_money(billed - paid)


def _name_maps():
    titles = {b["book_id"].upper(): b["title"] for b in storage.read_rows("books")}
    names = {s["student_id"].upper(): s["name"] for s in storage.read_rows("students")}
    return titles, names


# ================================================================ printing
def print_inventory_summary():
    counts = library.inventory_counts()
    active = len([l for l in storage.read_rows("loans") if l["loan_status"] == "Active"])
    print("\n=== INVENTORY SUMMARY ===")
    print(f"  Unique titles          : {counts['titles']}")
    print(f"  Total physical copies  : {counts['total']}")
    print(f"  Available copies       : {counts['available']}")
    print(f"  Issued copies          : {counts['issued']}")
    print(f"  Damaged copies         : {counts['damaged']}")
    print(f"  Lost copies            : {counts['lost']}")
    print(f"  Under repair           : {counts['under_repair']}")
    print(f"  Active loans           : {active}")
    check = (counts["available"] + counts["issued"] + counts["damaged"]
             + counts["lost"] + counts["under_repair"])
    print(f"  Consistency check      : {'OK' if check == counts['total'] else 'MISMATCH!'} "
          f"(parts add up to {check} of {counts['total']})")


def print_active_loans():
    titles, names = _name_maps()
    rows = []
    for loan in storage.read_rows("loans"):
        if loan["loan_status"] == "Active":
            rows.append([loan["loan_id"], loan["book_id"], titles.get(loan["book_id"].upper(), "?"),
                         loan["student_id"], names.get(loan["student_id"].upper(), "?"),
                         loan["issue_date"], loan["due_date"],
                         format_money(money_or_zero(loan["daily_rate_at_issue"]))])
    print("\n=== ACTIVE LOANS ===")
    print_table(["Loan", "Book", "Title", "Student", "Name", "Issued", "Due", "Rate/day"], rows)


def print_overdue(as_of=None):
    as_of = as_date(as_of or today())
    items = library.overdue_loans(as_of)
    rows = [[i["loan"]["loan_id"], i["book"]["book_id"], i["book"]["title"],
             i["student"]["student_id"], i["student"]["name"], i["loan"]["due_date"],
             i["late_days"], format_money(i["penalty"])] for i in items]
    print(f"\n=== OVERDUE BOOKS (as of {as_of.isoformat()}) ===")
    print_table(["Loan", "Book", "Title", "Student", "Name", "Due", "Days late", "Est. penalty"], rows)
    if items:
        total = sum((i["penalty"] for i in items), ZERO)
        print(f"\n  Estimated late penalties so far: {format_money(total)}")
        print("  (Estimates only - the real penalty is fixed on the return date.)")


def print_damaged_lost():
    rows = [[b["book_id"], b["title"], b["author"], b["status"], b["condition"],
             format_money(money_or_zero(b["purchase_cost"]))]
            for b in library.list_books() if b["status"] != "Available"]
    print("\n=== DAMAGED, LOST OR UNDER-REPAIR COPIES ===")
    print_table(["Book", "Title", "Author", "Status", "Condition", "Purchase cost"], rows)


def print_income_report():
    totals = financial_totals()
    print("\n=== INCOME REPORT ===")
    print("BILLED (charges raised on returned books)")
    print(f"  Rental charges     : {format_money(totals['rental'])}")
    print(f"  Late penalties     : {format_money(totals['late'])}")
    print(f"  Damage penalties   : {format_money(totals['damage'])}")
    print(f"  TOTAL BILLED       : {format_money(totals['billed'])}")
    print("\nCOLLECTED (money actually received)")
    print(f"  TOTAL COLLECTED    : {format_money(totals['collected'])}")
    print("\nOUTSTANDING (billed but not yet paid)")
    print(f"  TOTAL OUTSTANDING  : {format_money(totals['outstanding'])}")

    days = income_by_date()
    rows = [[day, format_money(v["billed"]), format_money(v["collected"])]
            for day, v in days.items()]
    print("\nDate-wise (billed by return date, collected by payment date):")
    print_table(["Date", "Billed", "Collected"], rows)
    print("\nNote: the margin is a pricing markup, NOT net profit. Net profit = money")
    print("collected minus the library's own costs, which are not tracked here.")


def print_outstanding():
    titles, names = _name_maps()
    rows = []
    for loan, balance in outstanding_loans():
        billed, paid, _ = _loan_money(loan)
        rows.append([loan["loan_id"], loan["student_id"], names.get(loan["student_id"].upper(), "?"),
                     titles.get(loan["book_id"].upper(), "?"), format_money(billed),
                     format_money(paid), format_money(balance)])
    print("\n=== LOANS WITH OUTSTANDING BALANCE ===")
    print_table(["Loan", "Student", "Name", "Title", "Billed", "Paid", "Balance"], rows)
    return len(rows)


def _print_loan_rows(loans):
    titles, _ = _name_maps()
    rows = []
    for loan in loans:
        billed, paid, balance = _loan_money(loan)
        rows.append([loan["loan_id"], loan["book_id"], titles.get(loan["book_id"].upper(), "?"),
                     loan["student_id"], loan["issue_date"], loan["due_date"],
                     loan["return_date"] or "-", loan["loan_status"],
                     format_money(billed), format_money(paid), format_money(balance)])
    print_table(["Loan", "Book", "Title", "Student", "Issued", "Due", "Returned",
                 "Status", "Billed", "Paid", "Balance"], rows)


def _print_payment_rows(payments):
    rows = [[p["payment_id"], p["loan_id"], p["payment_date"],
             format_money(money_or_zero(p["amount"])), p["payment_method"],
             p["reference_number"] or "-"] for p in payments]
    print_table(["Payment", "Loan", "Date", "Amount", "Method", "Reference"], rows)


def print_student_history(student_id):
    student = library.get_student(student_id)
    sid = student["student_id"].upper()
    loans = [l for l in storage.read_rows("loans") if l["student_id"].upper() == sid]
    loan_ids = {l["loan_id"].upper() for l in loans}
    payments = [p for p in storage.read_rows("payments") if p["loan_id"].upper() in loan_ids]
    print(f"\n=== HISTORY: {student['student_id']} - {student['name']} "
          f"(contact {student['contact_number']}) ===")
    print("Borrowing history:")
    _print_loan_rows(loans)
    print("\nPayment history:")
    _print_payment_rows(payments)


def print_book_history(book_id):
    book = library.get_book(book_id)
    loans = [l for l in storage.read_rows("loans") if l["book_id"].upper() == book["book_id"].upper()]
    print(f"\n=== ISSUE HISTORY: {book['book_id']} - {book['title']} "
          f"[{book['state']}] ===")
    _print_loan_rows(loans)


def print_loan_history(loan_id):
    loan = library.get_loan(loan_id)
    print(f"\n=== LOAN {loan['loan_id']} ===")
    _print_loan_rows([loan])
    print("\nPayments for this loan:")
    _print_payment_rows(library.payments_for_loan(loan["loan_id"]))
    if loan["loan_status"] == "Returned":
        print(f"\n  Outstanding balance: {format_money(library.outstanding_balance(loan['loan_id']))}")


def print_student_summary():
    """One line per student: loans, billed, paid, balance."""
    loans = storage.read_rows("loans")
    rows = []
    for student in library.list_students():
        mine = [l for l in loans if l["student_id"].upper() == student["student_id"].upper()]
        money = [_loan_money(l) for l in mine]
        rows.append([student["student_id"], student["name"], len(mine),
                     len([l for l in mine if l["loan_status"] == "Active"]),
                     format_money(sum((m[0] for m in money), ZERO)),
                     format_money(sum((m[1] for m in money), ZERO)),
                     format_money(sum((m[2] for m in money), ZERO))])
    print("\n=== STUDENT-WISE SUMMARY ===")
    print_table(["Student", "Name", "Loans", "Active", "Billed", "Paid", "Balance"], rows)

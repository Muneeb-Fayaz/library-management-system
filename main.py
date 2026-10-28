"""main.py - the terminal menu. Run this file:  python main.py

This file only talks to the librarian (prompts and printing). The real work is
done by library.py (logic), billing.py (money rules) and reports.py (reports).

Tip: type  cancel  at any prompt to go back to the main menu.
Single librarian only: CSV files cannot be shared safely between two running copies.
"""

import os
import sys

import billing
import library
import reports
import storage
from helpers import (
    format_money, parse_date, parse_money, parse_percent, parse_text, parse_id,
    parse_contact, parse_positive_int, print_table, today, money_or_zero,
)
from storage import DataError


class Cancelled(Exception):
    """Raised when the librarian types 'cancel'."""


# ================================================================ input helpers
def ask(prompt, parser=None, allow_empty=False):
    """Ask until the answer is valid. parser turns text into a clean value (or raises ValueError)."""
    while True:
        text = input(prompt).strip()
        if text.lower() == "cancel":
            raise Cancelled
        if text == "":
            if allow_empty:
                return ""
            print("  This cannot be empty (or type 'cancel').")
            continue
        if parser is None:
            return text
        try:
            return parser(text)
        except ValueError as error:
            print(f"  Error: {error}")


def ask_date(prompt):
    """Press Enter for today's date. Returns a date, or None meaning 'today'."""
    text = ask(f"{prompt} (Enter = today, or YYYY-MM-DD): ", allow_empty=True)
    if text == "":
        return None
    while True:
        try:
            return parse_date(text, "Date")
        except ValueError as error:
            print(f"  Error: {error}")
            text = ask(f"{prompt} (YYYY-MM-DD): ")


def ask_choice(title, options):
    """Show a numbered list and return the chosen item."""
    print(title)
    for number, option in enumerate(options, start=1):
        print(f"  {number}. {option}")
    while True:
        text = ask("Choose a number: ")
        if text.isdigit() and 1 <= int(text) <= len(options):
            return options[int(text) - 1]
        print(f"  Please enter a number from 1 to {len(options)}.")


def ask_yes_no(prompt):
    return ask(prompt + " (y/n): ", lambda t: _yes_no(t)) == "y"


def _yes_no(text):
    answer = text.strip().lower()
    if answer in ("y", "yes"):
        return "y"
    if answer in ("n", "no"):
        return "n"
    raise ValueError("Please answer y or n.")


def pause():
    input("\nPress Enter to return to the menu...")


# ================================================================ display helpers
def show_books(books):
    rows = [[b["book_id"], b["title"], b["author"], b["category"],
             format_money(money_or_zero(b["purchase_cost"])), b["margin_percent"] + "%",
             format_money(money_or_zero(b["daily_rate"])), b["condition"], b["state"]]
            for b in books]
    print_table(["Book ID", "Title", "Author", "Category", "Cost", "Margin", "Rate/day",
                 "Condition", "State"], rows)


def print_receipt(loan, book, student):
    print("\n" + "=" * 52)
    print("                 BOOK ISSUE RECEIPT")
    print("=" * 52)
    print(f"Loan ID      : {loan['loan_id']}")
    print(f"Book         : {book['book_id']} - {book['title']} by {book['author']}")
    print(f"Student      : {student['student_id']} - {student['name']} ({student['contact_number']})")
    print(f"Issue date   : {loan['issue_date']}")
    print(f"Due date     : {loan['due_date']}")
    print(f"Daily rate   : {format_money(money_or_zero(loan['daily_rate_at_issue']))} (locked for this loan)")
    print("-" * 52)
    print("Rental policy:")
    for line in billing.policy_lines():
        print(f"  - {line}")
    print("=" * 52)


def print_bill(loan, book, student_name, bill):
    rate = format_money(bill["daily_rate"])
    late_pct = billing.SETTINGS["late_fee_percent"]

    def line(label, value):
        print(f"{label:<42}: {value}")

    print("\n" + "=" * 60)
    print("                       RETURN BILL")
    print("=" * 60)
    print(f"Loan ID     : {loan['loan_id']}")
    print(f"Book        : {book['book_id']} - {book['title']}")
    print(f"Student     : {loan['student_id']} - {student_name}")
    print(f"Issued      : {loan['issue_date']}    Due: {loan['due_date']}")
    print("-" * 60)
    line("Daily rate (locked at issue)", rate)
    line("Chargeable days (issue + return day)", bill["chargeable_days"])
    line(f"Rental charge = {rate} x {bill['chargeable_days']}", format_money(bill["rental_charge"]))
    line("Late days", bill["late_days"])
    line(f"Late penalty = {bill['late_days']} x {rate} x {late_pct}%", format_money(bill["late_penalty"]))
    line("Damage category", bill["damage_label"])
    line(f"Damage penalty = {bill['damage_percent']}% of {format_money(bill['purchase_cost'])}",
         format_money(bill["damage_penalty"]))
    print("-" * 60)
    line("TOTAL AMOUNT DUE", format_money(bill["total"]))
    print("=" * 60)


# ================================================================ menu actions
def add_book():
    print("\n--- Add New Book ---  (type 'cancel' to go back)")
    details = {
        "title": ask("Title: ", lambda t: parse_text(t, "Title")),
        "author": ask("Author: ", lambda t: parse_text(t, "Author")),
        "category": ask("Category: ", lambda t: parse_text(t, "Category")),
        "publisher": ask("Publisher: ", lambda t: parse_text(t, "Publisher")),
        "purchase_cost": ask("Purchase cost (per copy): ", lambda t: parse_money(t, "Purchase cost")),
    }
    details["base_daily_rate"] = ask(
        "Base daily rental rate: ", lambda t: parse_money(t, "Base daily rate", allow_zero=False))
    default_margin = billing.SETTINGS["default_margin_percent"]
    text = ask(f"Margin percentage (Enter = {default_margin}): ",
               lambda t: parse_percent(t, "Margin"), allow_empty=True)
    details["margin_percent"] = default_margin if text == "" else text
    details["condition"] = ask_choice("Book condition:", library.BOOK_CONDITIONS)
    copies = ask("Number of copies: ", lambda t: parse_positive_int(t, "Number of copies", 100))

    new_books = library.add_books(details, copies)
    final_rate = money_or_zero(new_books[0]["daily_rate"])
    print(f"\nAdded {len(new_books)} cop{'y' if len(new_books) == 1 else 'ies'} of '{new_books[0]['title']}':")
    print("  Book IDs: " + ", ".join(b["book_id"] for b in new_books))
    print(f"  Base rate {format_money(details['base_daily_rate'])} + {details['margin_percent']}% margin"
          f" = final rate {format_money(final_rate)} per day")
    print("  (Margin is a pricing markup, not net profit.)")


def view_all_books():
    print("\n--- All Books ---")
    show_books(library.list_books())


def search_book():
    print("\n--- Search Book ---")
    term = ask("Search by ID, title, author or category: ")
    results = library.search_books(term)
    print(f"\n{len(results)} match(es):")
    show_books(results)


def check_available():
    print("\n--- Available Copies ---")
    show_books(library.available_copies())


def register_student():
    print("\n--- Register Student ---  (type 'cancel' to go back)")
    student_id = ask("Student ID: ", lambda t: parse_id(t, "Student ID"))
    name = ask("Name: ", lambda t: parse_text(t, "Name"))
    contact = ask("Contact number: ", parse_contact)
    row = library.add_student(student_id, name, contact)
    print(f"\nRegistered {row['student_id']} - {row['name']} on {row['registration_date']}.")


def view_students():
    print("\n--- Students ---")
    term = ask("Search by ID or name (Enter = show all): ", allow_empty=True)
    students = library.search_students(term) if term else library.list_students()
    rows = []
    for student in students:
        holding = library.student_active_loans(student["student_id"])
        titles = "; ".join(f"{b['book_id']} {b['title']}" for _, b in holding) or "-"
        rows.append([student["student_id"], student["name"], student["contact_number"],
                     student["registration_date"], titles])
    print_table(["Student ID", "Name", "Contact", "Registered", "Books currently borrowed"], rows)


def issue_book():
    print("\n--- Issue Book ---  (type 'cancel' to go back)")
    while True:
        student_id = ask("Student ID: ")
        try:
            student = library.get_student(student_id)
            break
        except ValueError as error:
            print(f"  Error: {error} Register the student first (option 5).")
    print(f"  Student: {student['name']}")
    show_books(library.available_copies())
    book_id = ask("Book copy ID to issue: ")
    issue_date = ask_date("Issue date")
    loan, book, student = library.issue_book(student["student_id"], book_id, issue_date)
    print_receipt(loan, book, student)


def return_book():
    print("\n--- Return Book ---  (type 'cancel' to go back)")
    reports.print_active_loans()
    identifier = ask("Loan ID or book copy ID being returned: ")
    return_date = ask_date("Return date")
    # Check the loan exists before asking the damage question.
    loan, book, _ = library.preview_return(identifier, return_date, "none")
    student = library.get_student(loan["student_id"])
    print(f"\nLoan {loan['loan_id']}: '{book['title']}' ({book['book_id']}) "
          f"issued to {student['name']} on {loan['issue_date']}, due {loan['due_date']}.")

    categories = [f"{c['label']} ({c['percent']}% of purchase cost)"
                  for c in billing.DAMAGE_CATEGORIES]
    chosen = ask_choice("\nInspect the book. Condition on return:", categories)
    damage_key = billing.DAMAGE_CATEGORIES[categories.index(chosen)]["key"]

    loan, book, bill = library.preview_return(identifier, return_date, damage_key)
    print_bill(loan, book, student["name"], bill)
    if not ask_yes_no("Confirm return and save this bill?"):
        print("Return cancelled. Nothing was saved.")
        return
    loan, book, bill = library.return_book(identifier, return_date, damage_key)
    print(f"\nLoan {loan['loan_id']} closed. Book {book['book_id']} is now "
          f"'{book['status']}' (condition: {book['condition']}).")
    print(f"Payment status: Unpaid - balance {format_money(bill['total'])}.")
    if bill["total"] > 0 and ask_yes_no("Record a payment now?"):
        take_payment(loan["loan_id"])


def view_active_loans():
    reports.print_active_loans()


def view_overdue():
    reports.print_overdue()


def view_damaged_lost():
    reports.print_damaged_lost()


def view_history():
    print("\n--- Loan and Payment History ---")
    choice = ask_choice("View history by:", [
        "Student (borrowing + payments)", "Book copy (issue history)",
        "Loan ID (bill + payments)", "All students summary"])
    if choice.startswith("Student ("):
        reports.print_student_history(ask("Student ID: "))
    elif choice.startswith("Book"):
        reports.print_book_history(ask("Book copy ID: "))
    elif choice.startswith("Loan"):
        reports.print_loan_history(ask("Loan ID: "))
    else:
        reports.print_student_summary()


def take_payment(loan_id=None):
    """Used by menu option 13 and after a return."""
    if loan_id is None:
        print("\n--- Record Payment ---  (type 'cancel' to go back)")
        if reports.print_outstanding() == 0:
            print("\nNothing is outstanding.")
            return
        loan_id = ask("Loan ID to pay: ")
    balance = library.outstanding_balance(loan_id)
    print(f"\nOutstanding balance on {loan_id.upper()}: {format_money(balance)}")
    if balance <= 0:
        print("This loan is already fully paid.")
        return
    amount = ask("Amount received (or 'full'): ",
                 lambda t: balance if t.lower() == "full" else parse_money(t, "Amount", False))
    method = ask_choice("Payment method:", library.PAYMENT_METHODS)
    reference = ask("Reference number (Enter to skip): ", allow_empty=True)
    paid_on = ask_date("Payment date")
    row = library.record_payment(loan_id, amount, method, reference, paid_on)
    left = library.outstanding_balance(row["loan_id"])
    print(f"\nPayment {row['payment_id']} saved: {format_money(money_or_zero(row['amount']))} "
          f"by {row['payment_method']}. Balance left: {format_money(left)}.")


def inventory_summary():
    reports.print_inventory_summary()


def income_report():
    reports.print_income_report()


def update_book():
    print("\n--- Update Book ---  (type 'cancel' to go back)")
    book = library.get_book(ask("Book copy ID: "))
    show_books([book])
    action = ask_choice("What do you want to change?", [
        "Details or prices", "Status (available / damaged / lost / under repair)"])
    if action.startswith("Status"):
        status = ask_choice("New status:", library.BOOK_STATUSES)
        updated = library.set_book_status(book["book_id"], status)
        print(f"\n{updated['book_id']} is now '{updated['status']}'.")
        return

    fields = {"Title": "title", "Author": "author", "Category": "category",
              "Publisher": "publisher", "Purchase cost": "purchase_cost",
              "Base daily rate": "base_daily_rate", "Margin percentage": "margin_percent"}
    label = ask_choice("Field to change:", list(fields))
    key = fields[label]
    value = ask(f"New {label.lower()}: ")
    same = [b for b in library.list_books()
            if (b["title"].lower(), b["author"].lower()) == (book["title"].lower(), book["author"].lower())]
    every = len(same) > 1 and ask_yes_no(f"Apply to all {len(same)} copies of this title?")
    changed = library.update_book_details(book["book_id"], {key: value}, all_copies=every)
    print(f"\nUpdated {len(changed)} cop{'y' if len(changed) == 1 else 'ies'}. "
          f"Current daily rate: {format_money(money_or_zero(changed[0]['daily_rate']))}")
    print("Books already on loan keep the rate they were issued at.")


# ================================================================ menu loop
MENU = [
    ("Add New Book", add_book),
    ("View All Books", view_all_books),
    ("Search Book", search_book),
    ("Check Available Books", check_available),
    ("Register Student", register_student),
    ("View Students", view_students),
    ("Issue Book", issue_book),
    ("Return Book", return_book),
    ("View Active Loans", view_active_loans),
    ("View Overdue Books", view_overdue),
    ("View Damaged or Lost Books", view_damaged_lost),
    ("View Loan and Payment History", view_history),
    ("Record Payment", take_payment),
    ("View Inventory Summary", inventory_summary),
    ("View Income Report", income_report),
    ("Update Book Details", update_book),
    ("Exit", None),
]


def show_menu():
    print("\n" + "=" * 44)
    print("   LIBRARY RENTAL MANAGEMENT SYSTEM")
    print("=" * 44)
    for number, (label, _) in enumerate(MENU, start=1):
        print(f" {number:>2}. {label}")


def startup():
    """Create missing files, check every file is readable, take a backup."""
    folder = os.environ.get("LIBRARY_DATA_DIR")
    if folder:
        storage.set_data_dir(folder)
    storage.ensure_files()
    for table in storage.FILE_NAMES:
        storage.read_rows(table)          # raises DataError if a file is damaged
    backup_folder = storage.backup_all()
    print(f"Data folder : {storage.DATA_DIR}")
    print(f"Backup saved: {backup_folder}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # so the rupee sign prints on Windows
    except (AttributeError, ValueError):
        pass
    try:
        startup()
    except DataError as error:
        print(f"\nCannot start: {error}")
        return 1

    while True:
        show_menu()
        try:
            choice = input("Enter your choice (1-17): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
            print("Invalid choice. Please enter a number from 1 to 17.")
            continue
        label, action = MENU[int(choice) - 1]
        if action is None:
            print("Goodbye! All records are saved in the CSV files.")
            return 0
        try:
            action()
        except Cancelled:
            print("\nCancelled. Nothing was changed.")
        except (ValueError, DataError) as error:
            print(f"\nError: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return 0
        try:
            pause()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return 0


if __name__ == "__main__":
    sys.exit(main())

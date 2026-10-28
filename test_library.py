"""test_library.py - automatic tests. Run with:  python -m unittest -v

Every test uses a brand-new TEMPORARY folder, so your real books.csv,
students.csv, loans.csv and payments.csv are never touched.
"""

import csv
import os
import tempfile
import unittest
from decimal import Decimal

import billing
import library
import reports
import storage

BOOK = {"title": "Python Basics", "author": "A. Writer", "category": "Programming",
        "publisher": "Open Press", "purchase_cost": "500", "base_daily_rate": "20",
        "margin_percent": "10"}


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original_dir = storage.DATA_DIR
        self.original_period = billing.SETTINGS["loan_period_days"]
        storage.set_data_dir(self.folder.name)
        storage.ensure_files()

    def tearDown(self):
        storage.set_data_dir(self.original_dir)
        billing.SETTINGS["loan_period_days"] = self.original_period
        self.folder.cleanup()

    def add_student(self, student_id="S001"):
        return library.add_student(student_id, "Asha Kumar", "9876543210")

    def add_book(self, copies=1):
        return library.add_books(BOOK, copies)


class TestBilling(unittest.TestCase):
    def test_final_rate(self):
        self.assertEqual(billing.calculate_final_rate("20", "10"), Decimal("22.00"))

    def test_spec_example_bill(self):
        # issue 1 Jan, due 5 Jan, return 6 Jan -> 6 chargeable days, 1 late day
        from datetime import date
        bill = billing.calculate_bill("22", date(2026, 1, 1), date(2026, 1, 5),
                                      date(2026, 1, 6), "500", "minor")
        self.assertEqual(bill["chargeable_days"], 6)
        self.assertEqual(bill["late_days"], 1)
        self.assertEqual(bill["rental_charge"], Decimal("132.00"))
        self.assertEqual(bill["late_penalty"], Decimal("2.20"))
        self.assertEqual(bill["damage_penalty"], Decimal("50.00"))
        self.assertEqual(bill["total"], Decimal("184.20"))

    def test_same_day_return_is_one_day_and_not_late(self):
        from datetime import date
        bill = billing.calculate_bill("22", date(2026, 1, 1), date(2026, 1, 8),
                                      date(2026, 1, 1), "500", "none")
        self.assertEqual(bill["chargeable_days"], 1)
        self.assertEqual(bill["late_days"], 0)
        self.assertEqual(bill["total"], Decimal("22.00"))

    def test_all_damage_categories(self):
        from datetime import date
        expected = {"none": "0.00", "minor": "50.00", "major": "150.00", "lost": "500.00"}
        for key, penalty in expected.items():
            bill = billing.calculate_bill("22", date(2026, 1, 1), date(2026, 1, 8),
                                          date(2026, 1, 2), "500", key)
            self.assertEqual(bill["damage_penalty"], Decimal(penalty), key)

    def test_return_before_issue_rejected(self):
        from datetime import date
        with self.assertRaises(ValueError):
            billing.calculate_bill("22", date(2026, 1, 5), date(2026, 1, 12),
                                   date(2026, 1, 4), "500", "none")


class TestBooks(LibraryTestCase):
    def test_add_and_search(self):
        rows = self.add_book()
        self.assertEqual(rows[0]["book_id"], "B0001")
        self.assertEqual(rows[0]["daily_rate"], "22.00")
        self.assertEqual(len(library.search_books("python")), 1)
        self.assertEqual(len(library.search_books("b0001")), 1)
        self.assertEqual(len(library.search_books("programming")), 1)
        self.assertEqual(len(library.search_books("writer")), 1)
        self.assertEqual(library.search_books("nothing-matches"), [])

    def test_multiple_copies_get_unique_ids(self):
        rows = self.add_book(copies=3)
        ids = [r["book_id"] for r in rows]
        self.assertEqual(ids, ["B0001", "B0002", "B0003"])
        counts = library.inventory_counts()
        self.assertEqual(counts["titles"], 1)
        self.assertEqual(counts["total"], 3)

    def test_duplicate_book_id_rejected(self):
        library.add_books(BOOK, 1, book_id="X1")
        with self.assertRaises(ValueError):
            library.add_books(BOOK, 1, book_id="x1")

    def test_negative_price_and_bad_percent_rejected(self):
        for field, bad in [("purchase_cost", "-5"), ("base_daily_rate", "-1"),
                           ("base_daily_rate", "0"), ("base_daily_rate", "abc"),
                           ("margin_percent", "150"), ("margin_percent", "-2")]:
            with self.assertRaises(ValueError, msg=f"{field}={bad}"):
                library.add_books(dict(BOOK, **{field: bad}))
        self.assertEqual(storage.read_rows("books"), [])

    def test_update_price_recalculates_rate_and_all_copies(self):
        self.add_book(copies=2)
        library.update_book_details("B0001", {"base_daily_rate": "30"}, all_copies=True)
        self.assertEqual([b["daily_rate"] for b in storage.read_rows("books")], ["33.00", "33.00"])

    def test_price_change_does_not_affect_existing_loan(self):
        self.add_book()
        self.add_student()
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-01")
        library.update_book_details("B0001", {"base_daily_rate": "100"})
        self.assertEqual(library.get_loan(loan["loan_id"])["daily_rate_at_issue"], "22.00")

    def test_status_change_blocked_while_issued(self):
        self.add_book()
        self.add_student()
        library.issue_book("S001", "B0001", "2026-01-01")
        with self.assertRaises(ValueError):
            library.set_book_status("B0001", "Lost")


class TestIssuing(LibraryTestCase):
    def test_issue_available_book(self):
        self.add_book()
        self.add_student()
        loan, book, student = library.issue_book("s001", "b0001", "2026-01-01")
        self.assertEqual(loan["loan_id"], "L0001")
        self.assertEqual(loan["due_date"], "2026-01-08")
        self.assertEqual(loan["loan_status"], "Active")
        self.assertEqual(library.get_book("B0001")["state"], "Issued")

    def test_issue_to_unregistered_student_rejected(self):
        self.add_book()
        with self.assertRaises(ValueError):
            library.issue_book("NOPE", "B0001", "2026-01-01")

    def test_issue_unavailable_book_rejected(self):
        self.add_book()
        self.add_student("S001")
        self.add_student("S002")
        library.issue_book("S001", "B0001", "2026-01-01")
        with self.assertRaises(ValueError):
            library.issue_book("S002", "B0001", "2026-01-02")
        self.assertEqual(len(storage.read_rows("loans")), 1)

    def test_issue_damaged_lost_or_repair_rejected(self):
        self.add_book(copies=3)
        self.add_student()
        for book_id, status in [("B0001", "Damaged"), ("B0002", "Lost"), ("B0003", "Under Repair")]:
            library.set_book_status(book_id, status)
            with self.assertRaises(ValueError, msg=status):
                library.issue_book("S001", book_id, "2026-01-01")

    def test_future_and_invalid_dates_rejected(self):
        self.add_book()
        self.add_student()
        with self.assertRaises(ValueError):
            library.issue_book("S001", "B0001", "2099-01-01")
        with self.assertRaises(ValueError):
            library.issue_book("S001", "B0001", "2026-02-30")
        with self.assertRaises(ValueError):
            library.issue_book("S001", "B0001", "not a date")

    def test_loan_period_is_configurable(self):
        self.add_book()
        self.add_student()
        billing.SETTINGS["loan_period_days"] = 14
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-01")
        self.assertEqual(loan["due_date"], "2026-01-15")


class TestReturns(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.add_book()
        self.add_student()

    def test_return_on_time(self):
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-01")
        _, book, bill = library.return_book(loan["loan_id"], "2026-01-05", "none")
        self.assertEqual(bill["late_days"], 0)
        self.assertEqual(bill["rental_charge"], Decimal("110.00"))   # 5 days x 22
        self.assertEqual(bill["total"], Decimal("110.00"))
        self.assertEqual(book["status"], "Available")
        self.assertEqual(library.get_book("B0001")["state"], "Available")

    def test_return_late_matches_spec_example(self):
        billing.SETTINGS["loan_period_days"] = 4        # due 5 Jan
        library.issue_book("S001", "B0001", "2026-01-01")
        loan, _, bill = library.return_book("B0001", "2026-01-06", "minor")   # by book ID
        self.assertEqual(bill["total"], Decimal("184.20"))
        saved = library.get_loan(loan["loan_id"])
        self.assertEqual(saved["total_amount_due"], "184.20")
        self.assertEqual(saved["damage_category"], "minor")
        self.assertEqual(saved["loan_status"], "Returned")

    def test_double_return_rejected(self):
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-01")
        library.return_book(loan["loan_id"], "2026-01-03", "none")
        with self.assertRaises(ValueError):
            library.return_book(loan["loan_id"], "2026-01-04", "none")

    def test_return_of_book_not_issued_rejected(self):
        with self.assertRaises(ValueError):
            library.return_book("B0001", "2026-01-04", "none")
        with self.assertRaises(ValueError):
            library.return_book("L9999", "2026-01-04", "none")

    def test_return_before_issue_date_rejected(self):
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-10")
        with self.assertRaises(ValueError):
            library.return_book(loan["loan_id"], "2026-01-09", "none")
        self.assertEqual(library.get_loan(loan["loan_id"])["loan_status"], "Active")

    def test_preview_saves_nothing(self):
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-01")
        library.preview_return(loan["loan_id"], "2026-01-05", "lost")
        self.assertEqual(library.get_loan(loan["loan_id"])["loan_status"], "Active")

    def test_damage_updates_book_status(self):
        for key, status in [("major", "Damaged"), ("lost", "Lost"), ("minor", "Available")]:
            self.tearDown()
            self.setUp()          # fresh folder, with one book and one student
            library.issue_book("S001", "B0001", "2026-01-01")
            library.return_book("B0001", "2026-01-02", key)
            self.assertEqual(library.get_book("B0001")["status"], status, key)

    def test_overdue_estimate(self):
        library.issue_book("S001", "B0001", "2026-01-01")        # due 2026-01-08
        items = library.overdue_loans("2026-01-11")               # 3 days late
        self.assertEqual(items[0]["late_days"], 3)
        self.assertEqual(items[0]["penalty"], Decimal("6.60"))    # 3 x 22 x 10%
        self.assertEqual(library.overdue_loans("2026-01-08"), [])


class TestPayments(LibraryTestCase):
    def returned_loan(self):
        self.add_book()
        self.add_student()
        billing.SETTINGS["loan_period_days"] = 4
        library.issue_book("S001", "B0001", "2026-01-01")
        loan, _, _ = library.return_book("B0001", "2026-01-06", "minor")   # total 184.20
        return loan["loan_id"]

    def test_partial_payments_and_balance(self):
        loan_id = self.returned_loan()
        self.assertEqual(library.outstanding_balance(loan_id), Decimal("184.20"))
        library.record_payment(loan_id, "100", "cash", "", "2026-01-06")
        self.assertEqual(library.outstanding_balance(loan_id), Decimal("84.20"))
        library.record_payment(loan_id, "84.20", "UPI", "TXN123", "2026-01-07")
        self.assertEqual(library.outstanding_balance(loan_id), Decimal("0.00"))
        self.assertEqual([p["payment_id"] for p in library.payments_for_loan(loan_id)],
                         ["P0001", "P0002"])

    def test_overpayment_and_bad_amounts_rejected(self):
        loan_id = self.returned_loan()
        for bad in ["184.21", "0", "-5", "abc"]:
            with self.assertRaises(ValueError, msg=bad):
                library.record_payment(loan_id, bad, "Cash")
        with self.assertRaises(ValueError):
            library.record_payment(loan_id, "10", "Bitcoin")
        self.assertEqual(library.payments_for_loan(loan_id), [])

    def test_cannot_pay_active_loan(self):
        self.add_book()
        self.add_student()
        loan, _, _ = library.issue_book("S001", "B0001", "2026-01-01")
        with self.assertRaises(ValueError):
            library.record_payment(loan["loan_id"], "10", "Cash")

    def test_payment_date_before_return_rejected(self):
        loan_id = self.returned_loan()
        with self.assertRaises(ValueError):
            library.record_payment(loan_id, "10", "Cash", "", "2026-01-02")

    def test_income_report_billed_vs_collected(self):
        loan_id = self.returned_loan()
        library.record_payment(loan_id, "100", "Cash", "", "2026-01-06")
        totals = reports.financial_totals()
        self.assertEqual(totals["rental"], Decimal("132.00"))
        self.assertEqual(totals["late"], Decimal("2.20"))
        self.assertEqual(totals["damage"], Decimal("50.00"))
        self.assertEqual(totals["billed"], Decimal("184.20"))
        self.assertEqual(totals["collected"], Decimal("100.00"))
        self.assertEqual(totals["outstanding"], Decimal("84.20"))
        days = reports.income_by_date()
        self.assertEqual(days["2026-01-06"]["billed"], Decimal("184.20"))
        self.assertEqual(days["2026-01-06"]["collected"], Decimal("100.00"))

    def test_active_loans_are_not_income(self):
        self.add_book()
        self.add_student()
        library.issue_book("S001", "B0001", "2026-01-01")
        totals = reports.financial_totals()
        self.assertEqual(totals["billed"], Decimal("0.00"))
        self.assertEqual(totals["outstanding"], Decimal("0.00"))


class TestStudents(LibraryTestCase):
    def test_register_search_duplicates_and_bad_input(self):
        self.add_student("S001")
        with self.assertRaises(ValueError):
            self.add_student("s001")
        with self.assertRaises(ValueError):
            library.add_student("S002", "Bad Phone", "12ab")
        with self.assertRaises(ValueError):
            library.add_student("S003", "   ", "9876543210")
        self.assertEqual(len(library.search_students("asha")), 1)
        self.assertEqual(len(library.search_students("s001")), 1)

    def test_books_currently_borrowed(self):
        self.add_book(copies=2)
        self.add_student()
        library.issue_book("S001", "B0001", "2026-01-01")
        held = library.student_active_loans("S001")
        self.assertEqual([book["book_id"] for _, book in held], ["B0001"])


class TestFilesAndIntegrity(LibraryTestCase):
    def test_missing_files_are_recreated(self):
        for name in storage.FILE_NAMES.values():
            os.remove(os.path.join(self.folder.name, name))
        storage.ensure_files()
        for table, name in storage.FILE_NAMES.items():
            with open(os.path.join(self.folder.name, name), newline="") as handle:
                self.assertEqual(next(csv.reader(handle)), storage.HEADERS[table])

    def test_missing_file_recreated_on_read(self):
        os.remove(storage.file_path("books"))
        self.assertEqual(storage.read_rows("books"), [])

    def test_wrong_header_detected(self):
        with open(storage.file_path("books"), "w", newline="") as handle:
            handle.write("id,name\n1,Oops\n")
        with self.assertRaises(storage.DataError):
            storage.read_rows("books")

    def test_wrong_column_count_detected(self):
        self.add_book()
        with open(storage.file_path("books"), "a", newline="") as handle:
            handle.write("B0002,Short row\n")
        with self.assertRaises(storage.DataError):
            storage.read_rows("books")

    def test_empty_file_detected(self):
        open(storage.file_path("loans"), "w").close()
        with self.assertRaises(storage.DataError):
            storage.read_rows("loans")

    def test_data_survives_reopening(self):
        self.add_book(copies=2)
        self.add_student()
        library.issue_book("S001", "B0001", "2026-01-01")
        # "Close and reopen": point at the same folder again and read fresh from disk.
        storage.set_data_dir(self.folder.name)
        storage.ensure_files()
        self.assertEqual(len(storage.read_rows("books")), 2)
        self.assertEqual(library.get_book("B0001")["state"], "Issued")
        self.assertEqual(library.get_student("S001")["name"], "Asha Kumar")

    def test_no_temp_files_left_behind(self):
        self.add_book()
        leftovers = [f for f in os.listdir(self.folder.name) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_commas_and_quotes_in_text_are_safe(self):
        library.add_books(dict(BOOK, title='Python, "Advanced" Tricks'))
        self.assertEqual(storage.read_rows("books")[0]["title"], 'Python, "Advanced" Tricks')

    def test_backup_creates_copies(self):
        self.add_book()
        folder = storage.backup_all()
        self.assertEqual(sorted(os.listdir(folder)), sorted(storage.FILE_NAMES.values()))

    def test_inventory_counts_match_loans(self):
        self.add_book(copies=5)
        self.add_student()
        library.issue_book("S001", "B0001", "2026-01-01")
        library.issue_book("S001", "B0002", "2026-01-01")
        library.set_book_status("B0003", "Damaged")
        library.set_book_status("B0004", "Lost")
        counts = library.inventory_counts()
        self.assertEqual(counts, {"titles": 1, "total": 5, "available": 1, "issued": 2,
                                  "damaged": 1, "lost": 1, "under_repair": 0})
        active = [l for l in storage.read_rows("loans") if l["loan_status"] == "Active"]
        self.assertEqual(counts["issued"], len(active))
        library.return_book("B0001", "2026-01-02", "none")
        counts = library.inventory_counts()
        self.assertEqual((counts["available"], counts["issued"]), (2, 1))
        self.assertEqual(sum(counts[k] for k in
                             ["available", "issued", "damaged", "lost", "under_repair"]),
                         counts["total"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

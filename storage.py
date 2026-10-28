"""storage.py - the ONLY file that touches the CSV files directly.

Why one file? If every module opened CSV files its own way, bugs would hide
everywhere. Here we keep reading, writing, backups and corruption checks together.

IMPORTANT: CSV has no transactions and no locking. This version is designed for
ONE librarian using ONE copy of the program at a time.
"""

import csv
import os
import shutil
import tempfile
from datetime import datetime

# By default the CSV files live next to this script. Tests change this folder
# (see set_data_dir) so they never touch the real library records.
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_BACKUPS = 10

FILE_NAMES = {
    "books": "books.csv",
    "students": "students.csv",
    "loans": "loans.csv",
    "payments": "payments.csv",
}

HEADERS = {
    "books": [
        "book_id", "title", "author", "category", "publisher", "purchase_cost",
        "base_daily_rate", "margin_percent", "daily_rate", "condition", "status",
    ],
    "students": ["student_id", "name", "contact_number", "registration_date"],
    "loans": [
        "loan_id", "book_id", "student_id", "issue_date", "due_date", "return_date",
        "daily_rate_at_issue", "chargeable_days", "late_days", "rental_charge",
        "late_penalty", "damage_category", "damage_penalty", "total_amount_due",
        "loan_status",
    ],
    "payments": [
        "payment_id", "loan_id", "payment_date", "amount", "payment_method",
        "reference_number",
    ],
}


class DataError(Exception):
    """Raised when a CSV file is missing, damaged or cannot be saved."""


def set_data_dir(path):
    """Point the program at a different folder (used by tests)."""
    global DATA_DIR
    DATA_DIR = path
    os.makedirs(DATA_DIR, exist_ok=True)


def file_path(table):
    return os.path.join(DATA_DIR, FILE_NAMES[table])


def ensure_files():
    """Create any missing CSV file with just its header row."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for table in FILE_NAMES:
        if not os.path.exists(file_path(table)):
            write_rows(table, [])


def read_rows(table):
    """Return all rows of a table as a list of dictionaries (all values are text)."""
    path = file_path(table)
    name = FILE_NAMES[table]
    if not os.path.exists(path):
        write_rows(table, [])  # recreate a missing file instead of crashing
    rows = []
    try:
        # utf-8-sig quietly removes the invisible marker Excel adds when saving
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != HEADERS[table]:
                raise DataError(
                    f"{name} has a missing or wrong header row.\n"
                    f"  Expected: {','.join(HEADERS[table])}\n"
                    f"  Found:    {','.join(reader.fieldnames or [])}\n"
                    f"  Fix the file, or restore a copy from the 'backups' folder."
                )
            for row in reader:
                # DictReader uses None for missing cells (too few columns)
                # and a None key for extra cells (too many columns).
                if None in row or None in row.values():
                    raise DataError(
                        f"{name}, line {reader.line_num}: wrong number of columns. "
                        f"Fix the file, or restore a copy from the 'backups' folder."
                    )
                rows.append(row)
    except (UnicodeDecodeError, csv.Error) as error:
        raise DataError(f"{name} could not be read ({error}). Restore a copy from 'backups'.")
    except PermissionError:
        raise DataError(f"{name} cannot be opened. Close it in Excel and try again.")
    return rows


def write_rows(table, rows):
    """Safely replace a whole CSV file.

    Steps: write a temporary file in the same folder -> flush to disk ->
    swap it over the real file. If anything fails half-way, the original file
    is untouched.
    """
    path = file_path(table)
    name = FILE_NAMES[table]
    handle_fd, temp_path = tempfile.mkstemp(dir=DATA_DIR, prefix=table + "_", suffix=".tmp")
    try:
        with os.fdopen(handle_fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADERS[table], extrasaction="raise")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except PermissionError:
        _remove_quietly(temp_path)
        raise DataError(f"{name} cannot be saved. Close it in Excel and try again.")
    except Exception:
        _remove_quietly(temp_path)
        raise


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def backup_all():
    """Copy every CSV into backups/<date_time>/ and keep only the newest MAX_BACKUPS."""
    root = os.path.join(DATA_DIR, "backups")
    folder = os.path.join(root, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    for table in FILE_NAMES:
        source = file_path(table)
        if os.path.exists(source):
            shutil.copy2(source, folder)
    old_folders = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    while len(old_folders) > MAX_BACKUPS:
        shutil.rmtree(os.path.join(root, old_folders.pop(0)), ignore_errors=True)
    return folder

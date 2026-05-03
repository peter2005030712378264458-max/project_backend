import sqlite3
from contextlib import contextmanager

from django.conf import settings


@contextmanager
def dashboard_connection():
    db_path = settings.ENERGY_DASHBOARD_DB
    if not db_path.exists():
        raise FileNotFoundError(f"Energy dashboard database not found: {db_path}")

    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def row_to_dict(row):
    return dict(row) if row is not None else None

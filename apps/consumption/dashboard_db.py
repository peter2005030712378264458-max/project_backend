from contextlib import contextmanager

from django.db import connection


class DashboardResult:
    def __init__(self, cursor):
        self.cursor = cursor

    def _row_to_dict(self, row):
        if row is None:
            return None
        columns = [column[0] for column in self.cursor.description]
        return dict(zip(columns, row))

    def fetchall(self):
        try:
            return [self._row_to_dict(row) for row in self.cursor.fetchall()]
        finally:
            self.cursor.close()

    def fetchone(self):
        try:
            return self._row_to_dict(self.cursor.fetchone())
        finally:
            self.cursor.close()


class DashboardConnection:
    def execute(self, sql, params=None):
        cursor = connection.cursor()
        cursor.execute(sql, params or [])
        return DashboardResult(cursor)


@contextmanager
def dashboard_connection():
    dashboard = DashboardConnection()
    try:
        yield dashboard
    finally:
        connection.close_if_unusable_or_obsolete()


def rows_to_dicts(rows):
    return rows


def row_to_dict(row):
    return row

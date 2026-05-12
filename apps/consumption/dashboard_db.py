from contextlib import contextmanager

from django.db import connections


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
    def __init__(self, alias="default"):
        self.alias = alias

    def execute(self, sql, params=None):
        cursor = connections[self.alias].cursor()
        cursor.execute(sql, params or [])
        return DashboardResult(cursor)


@contextmanager
def dashboard_connection(alias="default"):
    dashboard = DashboardConnection(alias)
    try:
        yield dashboard
    finally:
        connections[alias].close_if_unusable_or_obsolete()


def rows_to_dicts(rows):
    return rows


def row_to_dict(row):
    return row

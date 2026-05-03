from contextlib import contextmanager
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(value):
    if not IDENTIFIER_RE.fullmatch(value):
        raise ImproperlyConfigured(f"Unsafe PostgreSQL identifier: {value!r}")
    return f'"{value}"'


def dashboard_table(table_setting):
    schema = settings.DASHBOARD_POSTGRES["SCHEMA"]
    table = settings.DASHBOARD_POSTGRES[table_setting]
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"


@contextmanager
def dashboard_connection():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:
        raise ImproperlyConfigured(
            "PostgreSQL dashboard support requires psycopg. "
            "Install dependencies from requirements.txt."
        ) from error

    config = settings.DASHBOARD_POSTGRES
    if not config["PASSWORD"]:
        raise ImproperlyConfigured(
            "DASHBOARD_POSTGRES_PASSWORD is required. Put it in a local .env file."
        )

    connection = psycopg.connect(
        host=config["HOST"],
        port=config["PORT"],
        dbname=config["DB"],
        user=config["USER"],
        password=config["PASSWORD"],
        connect_timeout=config["CONNECT_TIMEOUT"],
        row_factory=dict_row,
    )
    try:
        yield connection
    finally:
        connection.close()


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def row_to_dict(row):
    return dict(row) if row is not None else None

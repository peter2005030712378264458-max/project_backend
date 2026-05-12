import os
import time

import psycopg


host = os.getenv("POSTGRES_HOST", "127.0.0.1")
port = os.getenv("POSTGRES_PORT", "15432")
dbname = os.getenv("DJANGO_POSTGRES_DB", os.getenv("POSTGRES_DB", "student"))
user = os.getenv("DJANGO_POSTGRES_USER", os.getenv("POSTGRES_USER", "student"))
password = os.getenv("DJANGO_POSTGRES_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
timeout = int(os.getenv("POSTGRES_WAIT_TIMEOUT", "60"))

deadline = time.time() + timeout
last_error = None

while time.time() < deadline:
    try:
        with psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=5,
        ):
            print(f"PostgreSQL is available: {user}@{host}:{port}/{dbname}", flush=True)
            raise SystemExit(0)
    except Exception as exc:
        last_error = exc
        print(f"Waiting for PostgreSQL at {host}:{port}/{dbname}: {exc}", flush=True)
        time.sleep(2)

raise SystemExit(f"PostgreSQL is not available after {timeout}s: {last_error}")

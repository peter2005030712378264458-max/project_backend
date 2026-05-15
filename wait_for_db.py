import os
import time
from pathlib import Path

import psycopg


def load_env_file(path):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name, default, *fallback_names):
    for env_name in (name, *fallback_names):
        value = os.getenv(env_name)
        if value is not None and value != "":
            return value
    return default


base_dir = Path(__file__).resolve().parent
load_env_file(base_dir / ".env")
load_env_file(base_dir / ".env.local")

host = env("POSTGRES_HOST", "127.0.0.1", "DASHBOARD_POSTGRES_HOST")
port = env("POSTGRES_PORT", "15432", "DASHBOARD_POSTGRES_PORT")
dbname = os.getenv("DJANGO_POSTGRES_DB", "student")
user = env("DJANGO_POSTGRES_USER", env("POSTGRES_USER", "student", "DASHBOARD_POSTGRES_USER"))
password = env("DJANGO_POSTGRES_PASSWORD", env("POSTGRES_PASSWORD", "", "DASHBOARD_POSTGRES_PASSWORD"))
timeout = int(os.getenv("POSTGRES_WAIT_TIMEOUT", "60"))
keepalive_options = {
    "keepalives": int(os.getenv("POSTGRES_KEEPALIVES", "1")),
    "keepalives_idle": int(os.getenv("POSTGRES_KEEPALIVES_IDLE", "30")),
    "keepalives_interval": int(os.getenv("POSTGRES_KEEPALIVES_INTERVAL", "10")),
    "keepalives_count": int(os.getenv("POSTGRES_KEEPALIVES_COUNT", "5")),
}

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
            **keepalive_options,
        ):
            print(f"PostgreSQL is available: {user}@{host}:{port}/{dbname}", flush=True)
            raise SystemExit(0)
    except Exception as exc:
        last_error = exc
        print(f"Waiting for PostgreSQL at {host}:{port}/{dbname}: {exc}", flush=True)
        time.sleep(2)

raise SystemExit(f"PostgreSQL is not available after {timeout}s: {last_error}")

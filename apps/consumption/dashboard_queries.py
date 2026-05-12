from __future__ import annotations

from dataclasses import dataclass
import re

from django.conf import settings

from .dashboard_db import dashboard_connection, row_to_dict, rows_to_dicts


POWER_METRICS = {
    "active_power_w_avg",
    "phase1_power_w_avg",
    "phase2_power_w_avg",
    "phase3_power_w_avg",
    "reactive_power_var_avg",
    "apparent_power_va_avg",
    "current_avg_a",
    "voltage_avg_v",
    "frequency_hz_avg",
    "meter_temperature_avg",
}
DAILY_POWER_METRICS = {
    "active_power_w_avg",
    "reactive_power_var_avg",
    "apparent_power_va_avg",
    "voltage_avg_v",
    "frequency_hz_avg",
    "meter_temperature_avg",
}

TIME_BUCKETS = {
    "hour": "hour",
    "day": "day",
    "week": "week",
}
TIME_BUCKET_INTERVALS = {
    "hour": "1 hour",
    "day": "1 day",
    "week": "1 week",
}
TIME_BUCKET_SECONDS = {
    "hour": 3600,
    "day": 86400,
    "week": 604800,
}

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
LEGACY_POWER_TABLE_ALIASES = {
    "power_1min": "electricity_sensor_readings",
}


@dataclass
class FilterSet:
    where_sql: str
    params: list[str]
    data_names: list[str] | None


def _normalize_blank(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _placeholders(values: list[str]) -> str:
    return ",".join("%s" for _ in values)


def _power_table() -> str:
    table_name = LEGACY_POWER_TABLE_ALIASES.get(settings.ENERGY_POWER_TABLE, settings.ENERGY_POWER_TABLE)
    if not IDENTIFIER_RE.match(table_name):
        raise ValueError("ENERGY_POWER_TABLE must be a table name or schema-qualified table name")
    return table_name


def _configured_table(setting_name: str) -> str:
    table_name = getattr(settings, setting_name)
    if not IDENTIFIER_RE.match(table_name):
        raise ValueError(f"{setting_name} must be a table name or schema-qualified table name")
    return table_name


def _hourly_table() -> str:
    return _configured_table("ENERGY_HOURLY_TABLE")


def _daily_table() -> str:
    return _configured_table("ENERGY_DAILY_TABLE")


def _analytics_db_alias() -> str:
    return settings.ENERGY_ANALYTICS_DB_ALIAS


def _power_view() -> str:
    return "power_readings"


def _power_readings_cte() -> str:
    source_table = _power_table()
    return f"""
        power_readings AS (
            SELECT
                   r.sensor_name::text AS data_name,
                   r.ts AS timestamp_iso,
                   COALESCE(r.pt, COALESCE(r.p1, 0) + COALESCE(r.p2, 0) + COALESCE(r.p3, 0)) AS active_power_w_avg,
                   COALESCE(r.pt, COALESCE(r.p1, 0) + COALESCE(r.p2, 0) + COALESCE(r.p3, 0)) AS active_power_w_max,
                   r.p1 AS phase1_power_w_avg,
                   r.p2 AS phase2_power_w_avg,
                   r.p3 AS phase3_power_w_avg,
                   COALESCE(r.qt, COALESCE(r.q1, 0) + COALESCE(r.q2, 0) + COALESCE(r.q3, 0)) AS reactive_power_var_avg,
                   COALESCE(r.st, COALESCE(r.s1, 0) + COALESCE(r.s2, 0) + COALESCE(r.s3, 0)) AS apparent_power_va_avg,
                   (COALESCE(r.i1, 0) + COALESCE(r.i2, 0) + COALESCE(r.i3, 0))
                       / NULLIF(
                           (CASE WHEN r.i1 IS NULL THEN 0 ELSE 1 END)
                         + (CASE WHEN r.i2 IS NULL THEN 0 ELSE 1 END)
                         + (CASE WHEN r.i3 IS NULL THEN 0 ELSE 1 END),
                           0
                       ) AS current_avg_a,
                   (COALESCE(r.u1, 0) + COALESCE(r.u2, 0) + COALESCE(r.u3, 0))
                       / NULLIF(
                           (CASE WHEN r.u1 IS NULL THEN 0 ELSE 1 END)
                         + (CASE WHEN r.u2 IS NULL THEN 0 ELSE 1 END)
                         + (CASE WHEN r.u3 IS NULL THEN 0 ELSE 1 END),
                           0
                   ) AS voltage_avg_v,
                   r.frequency AS frequency_hz_avg,
                   r.t AS meter_temperature_avg,
                   COALESCE(r.pt, COALESCE(r.p1, 0) + COALESCE(r.p2, 0) + COALESCE(r.p3, 0)) / 60000.0 AS energy_kwh_est
            FROM {source_table} r
        )
    """


def _metadata_ctes() -> str:
    return """
        sensor_metadata AS (
            SELECT DISTINCT
                   sd.sensor_name::text AS data_name,
                   sd.id AS sensor_id,
                   sd.roomid AS sensor_room_id,
                   r.room_number AS room,
                   r.floor_number AS floor,
                   b.building_name AS building,
                   r.room_description,
                   os.struc_name AS org_structure,
                   regexp_replace(sd.sensor_name::text, '\\s+Smart Meter$', '') AS feeder_name
            FROM sensor_directory sd
            LEFT JOIN structure.room r ON r.id = sd.roomid
            LEFT JOIN structure.building b ON b.id = r.buildingid
            LEFT JOIN structure.org_structure os ON os.id = r.org_structureid
        ),
        devices AS (
            SELECT
                   sm.data_name,
                   NULL::text AS raw_file,
                   'Power'::text AS source_type,
                   sm.sensor_id::text AS id,
                   sm.data_name AS device_name,
                   sm.data_name AS power_device_name,
                   COALESCE(NULLIF(sm.room, ''), sm.sensor_room_id::text) AS power_location,
                   sm.room_description AS power_description,
                   sm.feeder_name,
                   1::integer AS breaker_count,
                   CASE WHEN sm.room IS NULL OR sm.room = '' THEN 0 ELSE 1 END AS breaker_room_count,
                   CASE WHEN sm.floor IS NULL OR sm.floor = '' THEN 0 ELSE 1 END AS breaker_floor_count,
                   CASE WHEN sm.building IS NULL OR sm.building = '' THEN 0 ELSE 1 END AS breaker_building_count,
                   CASE WHEN sm.org_structure IS NULL OR sm.org_structure = '' THEN 0 ELSE 1 END AS consumer_count,
                   CASE WHEN sm.org_structure IS NULL OR sm.org_structure = '' THEN 0 ELSE 1 END AS consumer_class_count,
                   CASE WHEN sm.room IS NULL OR sm.room = '' THEN 0 ELSE 1 END AS consumer_room_count,
                   1::integer AS has_power_metadata,
                   1::integer AS has_breaker_map,
                   CASE WHEN sm.org_structure IS NULL OR sm.org_structure = '' THEN 0 ELSE 1 END AS has_consumer_map,
                   sm.data_name AS dashboard_label
            FROM sensor_metadata sm
        ),
        breakers AS (
            SELECT DISTINCT
                   sm.feeder_name AS feeder,
                   sm.feeder_name AS breaker,
                   sm.room,
                   sm.floor,
                   sm.building,
                   NULL::text AS phase1_color,
                   NULL::text AS phase2_color,
                   NULL::text AS phase3_color,
                   sm.feeder_name,
                   sm.data_name
            FROM sensor_metadata sm
        ),
        consumers AS (
            SELECT DISTINCT
                   sm.feeder_name AS feeder_code,
                   COALESCE(NULLIF(sm.room_description, ''), NULLIF(sm.org_structure, ''), sm.room) AS power_consumer,
                   sm.org_structure AS consumer_class,
                   sm.room,
                   NULL::text AS phase1_color,
                   NULL::text AS phase2_color,
                   NULL::text AS phase3_color,
                   sm.data_name
            FROM sensor_metadata sm
        )
    """


def _with_metadata(extra_ctes: str | None = None, include_power_readings: bool = True) -> str:
    ctes = _metadata_ctes()
    if include_power_readings:
        ctes = f"{_power_readings_cte()}, {ctes}"
    if extra_ctes:
        ctes = f"{ctes}, {extra_ctes}"
    return f"WITH {ctes}"


def _matching_data_names(connection, request) -> list[str] | None:
    direct_data_names = _split_values(request.query_params.get("data_name"))
    room = _normalize_blank(request.query_params.get("room"))
    consumer_class = _normalize_blank(request.query_params.get("consumer_class"))
    building = _normalize_blank(request.query_params.get("building"))
    floor = _normalize_blank(request.query_params.get("floor"))

    filtered_sets = []

    if direct_data_names:
        filtered_sets.append(set(direct_data_names))

    if room:
        rows = connection.execute(
            f"""
            {_with_metadata(include_power_readings=False)}
            SELECT DISTINCT data_name
            FROM (
                SELECT data_name FROM consumers WHERE room = %s AND data_name IS NOT NULL
                UNION
                SELECT data_name FROM breakers WHERE room = %s AND data_name IS NOT NULL
            ) room_matches
            """,
            [room, room],
        ).fetchall()
        filtered_sets.append({row["data_name"] for row in rows})

    if consumer_class:
        rows = connection.execute(
            f"""
            {_with_metadata(include_power_readings=False)}
            SELECT DISTINCT data_name
            FROM consumers
            WHERE data_name IS NOT NULL AND consumer_class = %s
            """,
            [consumer_class],
        ).fetchall()
        filtered_sets.append({row["data_name"] for row in rows})

    if building or floor:
        clauses = ["data_name IS NOT NULL"]
        params = []
        if building:
            clauses.append("building = %s")
            params.append(building)
        if floor:
            clauses.append("floor = %s")
            params.append(floor)
        rows = connection.execute(
            f"{_with_metadata(include_power_readings=False)} SELECT DISTINCT data_name FROM breakers WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        filtered_sets.append({row["data_name"] for row in rows})

    if not filtered_sets:
        return None

    data_names = set.intersection(*filtered_sets) if filtered_sets else set()
    return sorted(data_names)


def _build_power_filters(connection, request) -> FilterSet:
    clauses = []
    params: list[str] = []
    data_names = _matching_data_names(connection, request)

    if data_names is not None:
        if not data_names:
            return FilterSet("WHERE 1 = 0", [], data_names)
        clauses.append(f"data_name IN ({_placeholders(data_names)})")
        params.extend(data_names)

    date_from = _normalize_blank(request.query_params.get("from"))
    date_to = _normalize_blank(request.query_params.get("to"))

    if date_from:
        clauses.append("timestamp_iso >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp_iso <= %s")
        params.append(date_to)
    if not date_from and not date_to and settings.ENERGY_DEFAULT_LOOKBACK_HOURS > 0:
        clauses.append("timestamp_iso >= NOW() - (%s * INTERVAL '1 hour')")
        params.append(str(settings.ENERGY_DEFAULT_LOOKBACK_HOURS))

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return FilterSet(where_sql, params, data_names)


def _aggregate_where_sql(data_names: list[str] | None, request, alias: str = "a") -> tuple[str, list[str]]:
    clauses = []
    params: list[str] = []

    if data_names is not None:
        if not data_names:
            return "WHERE 1 = 0", []
        clauses.append(f"{alias}.sensor_name::text IN ({_placeholders(data_names)})")
        params.extend(data_names)

    date_from = _normalize_blank(request.query_params.get("from"))
    date_to = _normalize_blank(request.query_params.get("to"))

    if date_from:
        clauses.append(f"{alias}.bucket_start::timestamptz >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        clauses.append(f"{alias}.bucket_start::timestamptz <= %s::timestamptz")
        params.append(date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def _weighted_avg_sql(column: str, alias: str = "a") -> str:
    return (
        f"SUM({alias}.{column} * {alias}.points_count) "
        f"/ NULLIF(SUM({alias}.points_count) FILTER (WHERE {alias}.{column} IS NOT NULL), 0)"
    )


def _aggregate_source_for_bucket(bucket: str, metric: str = "active_power_w_avg") -> tuple[str, str, str]:
    if bucket == "hour":
        return _hourly_table(), "hour", "a.bucket_start"
    if bucket == "day" and metric in DAILY_POWER_METRICS:
        return _daily_table(), "day", "a.bucket_start::timestamptz"
    if bucket == "week" and metric in DAILY_POWER_METRICS:
        return _daily_table(), "week", "date_trunc('week', a.bucket_start::timestamptz)"
    return _hourly_table(), bucket, f"date_trunc('{bucket}', a.bucket_start)"


def _device_labels(connection, data_names: list[str]) -> dict[str, dict]:
    if not data_names:
        return {}
    rows = rows_to_dicts(
        connection.execute(
            f"""
            {_with_metadata(include_power_readings=False)}
            SELECT data_name, dashboard_label AS label, power_location AS location
            FROM devices
            WHERE data_name IN ({_placeholders(data_names)})
            """,
            data_names,
        ).fetchall()
    )
    return {row["data_name"]: row for row in rows}


def _alias_power_where(where_sql: str, alias: str) -> str:
    return (
        where_sql.replace("data_name", f"{alias}.data_name")
        .replace("timestamp_iso", f"{alias}.timestamp_iso")
    )


def _alias_raw_power_where(where_sql: str, alias: str) -> str:
    return (
        where_sql.replace("data_name", f"{alias}.sensor_name::text")
        .replace("timestamp_iso", f"{alias}.ts")
    )


def _raw_active_power(alias: str = "r") -> str:
    return f"COALESCE({alias}.pt, COALESCE({alias}.p1, 0) + COALESCE({alias}.p2, 0) + COALESCE({alias}.p3, 0))"


def _raw_voltage_avg(alias: str = "r") -> str:
    return f"""
        (COALESCE({alias}.u1, 0) + COALESCE({alias}.u2, 0) + COALESCE({alias}.u3, 0))
        / NULLIF(
            (CASE WHEN {alias}.u1 IS NULL THEN 0 ELSE 1 END)
          + (CASE WHEN {alias}.u2 IS NULL THEN 0 ELSE 1 END)
          + (CASE WHEN {alias}.u3 IS NULL THEN 0 ELSE 1 END),
            0
        )
    """


def _timeseries_bucket(request) -> str:
    granularity = request.query_params.get("granularity", "day")
    return TIME_BUCKETS.get(granularity, "day")


def _timeseries_interval(bucket: str) -> str:
    return TIME_BUCKET_INTERVALS[bucket]


def _timeseries_seconds(bucket: str) -> int:
    return TIME_BUCKET_SECONDS[bucket]


def get_filters():
    with dashboard_connection() as connection:
        devices = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT data_name, dashboard_label AS label, power_location AS location,
                       power_description AS description, has_breaker_map, has_consumer_map
                FROM devices
                WHERE source_type = 'Power'
                ORDER BY dashboard_label
                """
            ).fetchall()
        )
        rooms = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT room, COUNT(DISTINCT data_name) AS device_count
                FROM (
                    SELECT room, data_name FROM consumers WHERE room IS NOT NULL AND room != ''
                    UNION ALL
                    SELECT room, data_name FROM breakers WHERE room IS NOT NULL AND room != ''
                ) room_sources
                GROUP BY room
                ORDER BY room
                """
            ).fetchall()
        )
        consumer_classes = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT consumer_class, COUNT(*) AS consumer_count
                FROM consumers
                WHERE consumer_class IS NOT NULL AND consumer_class != ''
                GROUP BY consumer_class
                ORDER BY consumer_class
                """
            ).fetchall()
        )
        buildings = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT building, COUNT(DISTINCT data_name) AS device_count
                FROM breakers
                WHERE building IS NOT NULL AND building != ''
                GROUP BY building
                ORDER BY building
                """
            ).fetchall()
        )
        floors = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT floor, COUNT(DISTINCT data_name) AS device_count
                FROM breakers
                WHERE floor IS NOT NULL AND floor != ''
                GROUP BY floor
                ORDER BY floor
                """
            ).fetchall()
        )
        locations = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT power_location AS location, COUNT(*) AS device_count
                FROM devices
                WHERE power_location IS NOT NULL AND power_location != ''
                GROUP BY power_location
                ORDER BY power_location
                """
            ).fetchall()
        )
    with dashboard_connection(_analytics_db_alias()) as analytics_connection:
        date_range = row_to_dict(
            analytics_connection.execute(
                f"""
                SELECT MIN(bucket_start) AS date_from, MAX(bucket_start) AS date_to
                FROM {_hourly_table()}
                """
            ).fetchone()
        )

    return {
        "date_range": date_range,
        "devices": devices,
        "rooms": rooms,
        "consumer_classes": consumer_classes,
        "buildings": buildings,
        "floors": floors,
        "locations": locations,
        "metrics": sorted(POWER_METRICS),
    }


def get_summary(request):
    with dashboard_connection() as connection:
        data_names = _matching_data_names(connection, request)

    where_sql, params = _aggregate_where_sql(data_names, request)
    with dashboard_connection(_analytics_db_alias()) as connection:
        row = row_to_dict(
            connection.execute(
                f"""
                WITH filtered AS (
                    SELECT *
                    FROM {_hourly_table()} a
                    {where_sql}
                ),
                latest AS (
                    SELECT MAX(bucket_start) AS bucket_start
                    FROM filtered
                )
                SELECT COALESCE(SUM(points_count), 0) AS points,
                       COUNT(DISTINCT sensor_name) AS devices_count,
                       MIN(bucket_start) AS date_from,
                       MAX(bucket_start) AS date_to,
                       SUM(energy_kwh) AS total_energy_kwh,
                       {_weighted_avg_sql("active_power_w_avg", "filtered")} / 1000.0 AS avg_power_kw,
                       MAX(active_power_w_max) / 1000.0 AS max_power_kw,
                       {_weighted_avg_sql("voltage_avg_v", "filtered")} AS avg_voltage_v,
                       {_weighted_avg_sql("frequency_hz_avg", "filtered")} AS avg_frequency_hz,
                       (
                           SELECT {_weighted_avg_sql("active_power_w_avg", "current_rows")} / 1000.0
                           FROM filtered current_rows
                           JOIN latest ON latest.bucket_start = current_rows.bucket_start
                       ) AS current_power_kw,
                       MAX(bucket_start) AS timestamp_iso
                FROM filtered
                """,
                params,
            ).fetchone()
        )

    return row


def get_timeseries(request):
    metric = request.query_params.get("metric", "active_power_w_avg")
    if metric not in POWER_METRICS:
        metric = "active_power_w_avg"

    with dashboard_connection() as connection:
        bucket = _timeseries_bucket(request)
        data_names = _matching_data_names(connection, request)

    if data_names is not None and not data_names:
        return {"metric": metric, "granularity": bucket, "points": []}

    source_table, granularity, bucket_expr = _aggregate_source_for_bucket(bucket, metric)
    where_sql, params = _aggregate_where_sql(data_names, request)
    value_expr = _weighted_avg_sql(metric, "a")
    if metric.endswith("_power_w_avg"):
        value_expr = f"({value_expr}) / 1000.0"

    with dashboard_connection(_analytics_db_alias()) as connection:
        rows = rows_to_dicts(
            connection.execute(
                f"""
                SELECT {bucket_expr} AS timestamp,
                       {value_expr} AS value,
                       SUM(a.energy_kwh) AS energy_kwh,
                       SUM(a.points_count) AS points
                FROM {source_table} a
                {where_sql}
                GROUP BY {bucket_expr}
                ORDER BY timestamp
                """,
                params,
            ).fetchall()
        )

    return {"metric": metric, "granularity": granularity, "points": rows}


def get_top_devices(request, limit=10):
    with dashboard_connection() as connection:
        data_names = _matching_data_names(connection, request)

    if data_names is not None and not data_names:
        return []

    where_sql, params = _aggregate_where_sql(data_names, request)
    with dashboard_connection(_analytics_db_alias()) as connection:
        power_rows = rows_to_dicts(
            connection.execute(
                f"""
                SELECT a.sensor_name::text AS data_name,
                       SUM(a.energy_kwh) AS energy_kwh,
                       {_weighted_avg_sql("active_power_w_avg", "a")} / 1000.0 AS avg_power_kw,
                       MAX(a.active_power_w_max) / 1000.0 AS max_power_kw
                FROM {_hourly_table()} a
                {where_sql}
                GROUP BY a.sensor_name
                ORDER BY energy_kwh DESC NULLS LAST
                LIMIT %s
                """,
                [*params, limit],
            ).fetchall()
        )

    with dashboard_connection() as connection:
        labels = _device_labels(connection, [row["data_name"] for row in power_rows])

    rows = []
    for row in power_rows:
        device = labels.get(row["data_name"], {})
        rows.append(
            {
                **row,
                "label": device.get("label") or row["data_name"],
                "location": device.get("location"),
            }
        )
    return rows


def get_device_detail(request, data_name):
    with dashboard_connection() as connection:
        device = row_to_dict(
            connection.execute(
                f"{_with_metadata(include_power_readings=False)} SELECT * FROM devices WHERE data_name = %s",
                [data_name],
            ).fetchone()
        )
        if device is None:
            return None

        summary_request = _RequestProxy(request, data_name)
        summary = get_summary(summary_request)
        breakers = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT breaker, room, floor, building, phase1_color, phase2_color, phase3_color
                FROM breakers
                WHERE data_name = %s
                ORDER BY room, breaker
                LIMIT 200
                """,
                [data_name],
            ).fetchall()
        )
        consumers = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT power_consumer, consumer_class, room, phase1_color, phase2_color, phase3_color
                FROM consumers
                WHERE data_name = %s
                ORDER BY consumer_class, room, power_consumer
                LIMIT 200
                """,
                [data_name],
            ).fetchall()
        )
    return {
        "device": device,
        "summary": summary,
        "breakers": breakers,
        "consumers": consumers,
    }


def get_room_loads(request, limit=12):
    with dashboard_connection() as connection:
        data_names = _matching_data_names(connection, request)
        if data_names is not None and not data_names:
            return []

        room_params = []
        room_filter = ""
        if data_names is not None:
            room_filter = f"WHERE data_name IN ({_placeholders(data_names)})"
            room_params = data_names

        room_rows = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(include_power_readings=False)}
                SELECT data_name, room
                FROM breakers
                {room_filter}
                """,
                room_params,
            ).fetchall()
        )

    sensor_rooms = {
        row["data_name"]: row["room"]
        for row in room_rows
        if row.get("data_name") and row.get("room")
    }
    if not sensor_rooms:
        return []

    where_sql, params = _aggregate_where_sql(list(sensor_rooms), request)
    with dashboard_connection(_analytics_db_alias()) as connection:
        power_rows = rows_to_dicts(
            connection.execute(
                f"""
                SELECT a.sensor_name::text AS data_name,
                       SUM(a.points_count) AS points_count,
                       SUM(a.energy_kwh) AS energy_kwh,
                       {_weighted_avg_sql("active_power_w_avg", "a")} / 1000.0 AS avg_power_kw,
                       MAX(a.active_power_w_max) / 1000.0 AS max_power_kw
                FROM {_hourly_table()} a
                {where_sql}
                GROUP BY a.sensor_name
                """,
                params,
            ).fetchall()
        )

    rooms: dict[str, dict] = {}
    for row in power_rows:
        room = sensor_rooms.get(row["data_name"])
        if not room:
            continue
        room_bucket = rooms.setdefault(
            room,
            {
                "room": room,
                "devices": set(),
                "points_count": 0,
                "energy_kwh": 0,
                "weighted_power_sum": 0,
                "max_power_kw": None,
            },
        )
        points_count = row.get("points_count") or 0
        avg_power_kw = row.get("avg_power_kw") or 0
        energy_kwh = row.get("energy_kwh") or 0
        room_bucket["devices"].add(row["data_name"])
        room_bucket["points_count"] += points_count
        room_bucket["energy_kwh"] += energy_kwh
        room_bucket["weighted_power_sum"] += avg_power_kw * points_count
        if row.get("max_power_kw") is not None:
            room_bucket["max_power_kw"] = (
                row["max_power_kw"]
                if room_bucket["max_power_kw"] is None
                else max(room_bucket["max_power_kw"], row["max_power_kw"])
            )

    rows = []
    for room_bucket in rooms.values():
        points_count = room_bucket["points_count"]
        rows.append(
            {
                "room": room_bucket["room"],
                "devices_count": len(room_bucket["devices"]),
                "energy_kwh": room_bucket["energy_kwh"],
                "avg_power_kw": room_bucket["weighted_power_sum"] / points_count if points_count else None,
                "max_power_kw": room_bucket["max_power_kw"],
            }
        )

    return sorted(rows, key=lambda row: row["energy_kwh"] or 0, reverse=True)[:limit]


class _RequestProxy:
    def __init__(self, request, data_name):
        self.query_params = request.query_params.copy()
        self.query_params["data_name"] = data_name

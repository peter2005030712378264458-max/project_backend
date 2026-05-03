from __future__ import annotations

from dataclasses import dataclass

from .dashboard_db import dashboard_connection, dashboard_table, row_to_dict, rows_to_dicts


READINGS_TABLE = dashboard_table("READINGS_TABLE")
SENSOR_TABLE = dashboard_table("SENSOR_TABLE")
BROAD_QUERY_RAW_LIMIT = 250000

UNAVAILABLE_FILTERS = {
    "consumer_class": "В новой БД нет справочника классов потребителей.",
    "building": "В новой БД нет справочника зданий.",
    "floor": "В новой БД нет справочника этажей.",
    "location": "В новой БД нет отдельной локации счетчика.",
}

UNAVAILABLE_RELATIONS = {
    "breakers": "В новой БД нет справочника автоматов.",
    "consumers": "В новой БД нет справочника потребителей.",
}

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

METRIC_COLUMNS = {
    "active_power_w_avg": "active_power_w_avg",
    "phase1_power_w_avg": "phase1_power_w_avg",
    "phase2_power_w_avg": "phase2_power_w_avg",
    "phase3_power_w_avg": "phase3_power_w_avg",
    "reactive_power_var_avg": "reactive_power_var_avg",
    "apparent_power_va_avg": "apparent_power_va_avg",
    "current_avg_a": "current_avg_a",
    "voltage_avg_v": "voltage_avg_v",
    "frequency_hz_avg": "frequency_hz_avg",
    "meter_temperature_avg": "meter_temperature_avg",
}

SUM_TIMESERIES_METRICS = {
    "active_power_w_avg",
    "reactive_power_var_avg",
    "apparent_power_va_avg",
}

SENSOR_MINUTES_SELECT = """
    SELECT
        r.sensor_name AS data_name,
        COALESCE(r.roomid::text, 'без помещения') AS room,
        date_trunc('minute', r.ts) AS timestamp_minute,
        COUNT(*) AS samples,
        AVG(r.pt) AS active_power_w_avg,
        MIN(r.pt) AS active_power_w_min,
        MAX(r.pt) AS active_power_w_max,
        AVG(r.p1) AS phase1_power_w_avg,
        AVG(r.p2) AS phase2_power_w_avg,
        AVG(r.p3) AS phase3_power_w_avg,
        AVG(r.qt) AS reactive_power_var_avg,
        AVG(r.st) AS apparent_power_va_avg,
        AVG((
            COALESCE(r.i1, 0) + COALESCE(r.i2, 0) + COALESCE(r.i3, 0)
        ) / NULLIF(
            (CASE WHEN r.i1 IS NULL THEN 0 ELSE 1 END) +
            (CASE WHEN r.i2 IS NULL THEN 0 ELSE 1 END) +
            (CASE WHEN r.i3 IS NULL THEN 0 ELSE 1 END),
            0
        )) AS current_avg_a,
        AVG((
            COALESCE(r.u1, 0) + COALESCE(r.u2, 0) + COALESCE(r.u3, 0)
        ) / NULLIF(
            (CASE WHEN r.u1 IS NULL THEN 0 ELSE 1 END) +
            (CASE WHEN r.u2 IS NULL THEN 0 ELSE 1 END) +
            (CASE WHEN r.u3 IS NULL THEN 0 ELSE 1 END),
            0
        )) AS voltage_avg_v,
        AVG(r.frequency) AS frequency_hz_avg,
        AVG(r.t) AS meter_temperature_avg
    FROM {readings_source} r
    {where_sql}
    GROUP BY r.sensor_name, COALESCE(r.roomid::text, 'без помещения'), date_trunc('minute', r.ts)
"""


@dataclass
class FilterSet:
    where_sql: str
    params: list[str]
    data_names: list[str] | None
    default_limited: bool
    broad_query: bool


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


def _build_power_filters(request, alias: str = "r") -> FilterSet:
    clauses = []
    params: list[str] = []
    data_names = _split_values(request.query_params.get("data_name"))
    room = _normalize_blank(request.query_params.get("room"))
    date_from = _normalize_blank(request.query_params.get("from"))
    date_to = _normalize_blank(request.query_params.get("to"))
    default_limited = False
    broad_query = not data_names and not room

    if data_names:
        clauses.append(f"{alias}.sensor_name IN ({_placeholders(data_names)})")
        params.extend(data_names)

    if room:
        clauses.append(f"{alias}.roomid::text = %s")
        params.append(room)

    if date_from:
        clauses.append(f"{alias}.ts >= %s")
        params.append(date_from)
    elif not date_to:
        clauses.append(
            f"""
            {alias}.ts >= (
                SELECT latest.ts - INTERVAL '1 day'
                FROM {READINGS_TABLE} latest
                ORDER BY latest.id DESC
                LIMIT 1
            )
            """
        )
        default_limited = True

    if date_to:
        clauses.append(f"{alias}.ts <= %s")
        params.append(date_to)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return FilterSet(where_sql, params, data_names or None, default_limited, broad_query)


def _readings_source(filters: FilterSet) -> str:
    if not filters.broad_query:
        return READINGS_TABLE

    return f"""
        (
            SELECT *
            FROM {READINGS_TABLE}
            ORDER BY id DESC
            LIMIT {BROAD_QUERY_RAW_LIMIT}
        )
    """


def _sensor_minutes_sql(filters: FilterSet) -> str:
    return SENSOR_MINUTES_SELECT.format(
        readings_source=_readings_source(filters),
        where_sql=filters.where_sql,
    )


def _timestamp_iso(expression: str) -> str:
    return f"to_char(({expression}) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"


def get_filters():
    with dashboard_connection() as connection:
        devices = rows_to_dicts(
            connection.execute(
                f"""
                SELECT
                       sd.sensor_name AS data_name,
                       sd.sensor_name AS label,
                       NULL::text AS location,
                       NULL::text AS description,
                       FALSE AS has_breaker_map,
                       FALSE AS has_consumer_map
                FROM {SENSOR_TABLE} sd
                ORDER BY sd.sensor_name
                """
            ).fetchall()
        )
        rooms = rows_to_dicts(
            connection.execute(
                f"""
                SELECT COALESCE(sd.roomid::text, 'без помещения') AS room,
                       COUNT(*) AS device_count
                FROM {SENSOR_TABLE} sd
                GROUP BY COALESCE(sd.roomid::text, 'без помещения')
                ORDER BY room
                """
            ).fetchall()
        )
        date_range = row_to_dict(
            connection.execute(
                f"""
                WITH latest AS (
                    SELECT r.sensor_name AS data_name,
                           r.ts AS date_to
                    FROM {READINGS_TABLE} r
                    ORDER BY r.id DESC
                    LIMIT 1
                )
                SELECT {_timestamp_iso("date_to - INTERVAL '1 day'")} AS date_from,
                       {_timestamp_iso('date_to')} AS date_to,
                       data_name AS default_data_name
                FROM latest
                """
            ).fetchone()
        )

    return {
        "date_range": date_range,
        "devices": devices,
        "rooms": rooms,
        "consumer_classes": [],
        "buildings": [],
        "floors": [],
        "locations": [],
        "metrics": sorted(POWER_METRICS),
        "default_period": "24h",
        "default_data_name": date_range.get("default_data_name") if date_range else None,
        "unavailable_filters": UNAVAILABLE_FILTERS,
        "unavailable_relations": UNAVAILABLE_RELATIONS,
    }


def get_summary(request):
    with dashboard_connection() as connection:
        filters = _build_power_filters(request)
        readings_source = _readings_source(filters)
        row = row_to_dict(
            connection.execute(
                f"""
                SELECT COUNT(*) AS points,
                       COUNT(DISTINCT r.sensor_name) AS devices_count,
                       {_timestamp_iso('MIN(r.ts)')} AS date_from,
                       {_timestamp_iso('MAX(r.ts)')} AS date_to,
                       SUM(r.pt / 60000.0) AS total_energy_kwh,
                       AVG(r.pt) / 1000.0 AS avg_power_kw,
                       MAX(r.pt) / 1000.0 AS max_power_kw,
                       AVG((
                           COALESCE(r.u1, 0) + COALESCE(r.u2, 0) + COALESCE(r.u3, 0)
                       ) / NULLIF(
                           (CASE WHEN r.u1 IS NULL THEN 0 ELSE 1 END) +
                           (CASE WHEN r.u2 IS NULL THEN 0 ELSE 1 END) +
                           (CASE WHEN r.u3 IS NULL THEN 0 ELSE 1 END),
                           0
                       )) AS avg_voltage_v,
                       AVG(r.frequency) AS avg_frequency_hz
                FROM {readings_source} r
                {filters.where_sql}
                """,
                filters.params,
            ).fetchone()
        )
        latest = row_to_dict(
            connection.execute(
                f"""
                WITH latest AS (
                    SELECT DISTINCT ON (r.sensor_name)
                           r.sensor_name,
                           r.ts,
                           r.pt
                    FROM {readings_source} r
                    {filters.where_sql}
                    ORDER BY r.sensor_name, r.ts DESC
                )
                SELECT SUM(pt) / 1000.0 AS current_power_kw,
                       {_timestamp_iso('MAX(ts)')} AS timestamp_iso
                FROM latest
                """,
                filters.params,
            ).fetchone()
        )

    return {
        **(row or {}),
        **(latest or {}),
        "default_limited": filters.default_limited,
        "broad_limited": filters.broad_query,
    }


def get_timeseries(request):
    metric = request.query_params.get("metric", "active_power_w_avg")
    if metric not in POWER_METRICS:
        metric = "active_power_w_avg"

    aggregate = "SUM" if metric in SUM_TIMESERIES_METRICS else "AVG"
    metric_column = METRIC_COLUMNS[metric]

    with dashboard_connection() as connection:
        filters = _build_power_filters(request)
        sensor_minutes_sql = _sensor_minutes_sql(filters)
        rows = rows_to_dicts(
            connection.execute(
                f"""
                WITH sensor_minutes AS (
                    {sensor_minutes_sql}
                )
                SELECT {_timestamp_iso('timestamp_minute')} AS timestamp,
                       {aggregate}({metric_column}) AS value
                FROM sensor_minutes
                GROUP BY timestamp_minute
                ORDER BY timestamp_minute
                LIMIT 20000
                """,
                filters.params,
            ).fetchall()
        )

    return {"metric": metric, "points": rows}


def get_top_devices(request, limit=10):
    with dashboard_connection() as connection:
        filters = _build_power_filters(request)
        readings_source = _readings_source(filters)
        rows = rows_to_dicts(
            connection.execute(
                f"""
                SELECT r.sensor_name AS data_name,
                       r.sensor_name AS label,
                       NULL::text AS location,
                       SUM(r.pt / 60000.0) AS energy_kwh,
                       AVG(r.pt) / 1000.0 AS avg_power_kw,
                       MAX(r.pt) / 1000.0 AS max_power_kw
                FROM {readings_source} r
                {filters.where_sql}
                GROUP BY r.sensor_name
                ORDER BY energy_kwh DESC
                LIMIT %s
                """,
                [*filters.params, limit],
            ).fetchall()
        )
    return rows


def get_device_detail(request, data_name):
    with dashboard_connection() as connection:
        device = row_to_dict(
            connection.execute(
                f"""
                SELECT sd.sensor_name AS data_name,
                       sd.sensor_name AS dashboard_label,
                       sd.sensor_name AS device_name,
                       sd.sensor_name AS power_device_name,
                       sd.id,
                       sd.roomid::text AS room,
                       sd.device_listid,
                       NULL::text AS power_location,
                       NULL::text AS power_description,
                       NULL::text AS feeder_name,
                       FALSE AS has_breaker_map,
                       FALSE AS has_consumer_map
                FROM {SENSOR_TABLE} sd
                WHERE sd.sensor_name = %s
                """,
                [data_name],
            ).fetchone()
        )
        if device is None:
            return None

        summary_request = _RequestProxy(request, data_name)
        summary = get_summary(summary_request)

    return {
        "device": device,
        "summary": summary,
        "breakers": [],
        "consumers": [],
        "unavailable_relations": UNAVAILABLE_RELATIONS,
    }


def get_room_loads(request, limit=12):
    with dashboard_connection() as connection:
        filters = _build_power_filters(request)
        readings_source = _readings_source(filters)
        rows = rows_to_dicts(
            connection.execute(
                f"""
                SELECT COALESCE(r.roomid::text, 'без помещения') AS room,
                       COUNT(DISTINCT r.sensor_name) AS devices_count,
                       SUM(r.pt / 60000.0) AS energy_kwh,
                       AVG(r.pt) / 1000.0 AS avg_power_kw,
                       MAX(r.pt) / 1000.0 AS max_power_kw
                FROM {readings_source} r
                {filters.where_sql}
                GROUP BY COALESCE(r.roomid::text, 'без помещения')
                ORDER BY energy_kwh DESC
                LIMIT %s
                """,
                [*filters.params, limit],
            ).fetchall()
        )
    return rows


class _RequestProxy:
    def __init__(self, request, data_name):
        self.query_params = request.query_params.copy()
        self.query_params["data_name"] = data_name

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

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


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
    table_name = settings.ENERGY_POWER_TABLE
    if not IDENTIFIER_RE.match(table_name):
        raise ValueError("ENERGY_POWER_TABLE must be a table name or schema-qualified table name")
    return table_name


def _metadata_ctes() -> str:
    return """
        feeder_rooms AS (
            SELECT DISTINCT
                   f.id AS feeder_id,
                   f.feeder_name AS data_name,
                   ep.panel_name,
                   ep.panel_description,
                   r.room_number AS room,
                   r.floor_number AS floor,
                   b.building_name AS building
            FROM structure.feeder f
            LEFT JOIN structure.feeder_electrical_panel fep ON fep.feederid = f.id
            LEFT JOIN structure.electrical_panel ep ON ep.id = fep.electrical_panelid
            LEFT JOIN structure.room r ON r.id = ep.roomid
            LEFT JOIN structure.building b ON b.id = r.buildingid
            UNION
            SELECT DISTINCT
                   f.id AS feeder_id,
                   f.feeder_name AS data_name,
                   NULL::varchar AS panel_name,
                   NULL::varchar AS panel_description,
                   r.room_number AS room,
                   r.floor_number AS floor,
                   b.building_name AS building
            FROM structure.feeder f
            LEFT JOIN structure.room_feeder rf ON rf.feederid = f.id
            LEFT JOIN structure.room r ON r.id = rf.roomid
            LEFT JOIN structure.building b ON b.id = r.buildingid
        ),
        devices AS (
            SELECT
                   f.feeder_name AS data_name,
                   NULL::text AS raw_file,
                   'Power'::text AS source_type,
                   f.id::text AS id,
                   f.feeder_name AS device_name,
                   f.feeder_name AS power_device_name,
                   STRING_AGG(DISTINCT NULLIF(fr.room, ''), ', ') AS power_location,
                   f.feeder_description AS power_description,
                   f.feeder_name AS feeder_name,
                   COUNT(DISTINCT psl.id)::integer AS breaker_count,
                   COUNT(DISTINCT NULLIF(fr.room, ''))::integer AS breaker_room_count,
                   COUNT(DISTINCT NULLIF(fr.floor, ''))::integer AS breaker_floor_count,
                   COUNT(DISTINCT NULLIF(fr.building, ''))::integer AS breaker_building_count,
                   COUNT(DISTINCT fp.id)::integer AS consumer_count,
                   COUNT(DISTINCT NULLIF(fp.purpose_name, ''))::integer AS consumer_class_count,
                   COUNT(DISTINCT NULLIF(fr.room, ''))::integer AS consumer_room_count,
                   1::integer AS has_power_metadata,
                   CASE WHEN COUNT(DISTINCT fr.panel_name) > 0 THEN 1 ELSE 0 END AS has_breaker_map,
                   CASE WHEN COUNT(DISTINCT fp.id) > 0 THEN 1 ELSE 0 END AS has_consumer_map,
                   COALESCE(NULLIF(f.feeder_description, ''), f.feeder_name) AS dashboard_label
            FROM structure.feeder f
            LEFT JOIN feeder_rooms fr ON fr.feeder_id = f.id
            LEFT JOIN structure.feeder_electrical_panel fep ON fep.feederid = f.id
            LEFT JOIN structure.power_supply_lines psl ON psl.electrical_panelid = fep.electrical_panelid
            LEFT JOIN structure.feeder_purpose fp ON fp.id = psl.feeder_purposeid
            GROUP BY f.id, f.feeder_name, f.feeder_description
        ),
        breakers AS (
            SELECT DISTINCT
                   f.feeder_name AS feeder,
                   COALESCE(psl.id::text, fr.panel_name) AS breaker,
                   fr.room,
                   fr.floor,
                   fr.building,
                   NULL::text AS phase1_color,
                   NULL::text AS phase2_color,
                   NULL::text AS phase3_color,
                   f.feeder_name AS feeder_name,
                   f.feeder_name AS data_name
            FROM structure.feeder f
            LEFT JOIN feeder_rooms fr ON fr.feeder_id = f.id
            LEFT JOIN structure.feeder_electrical_panel fep ON fep.feederid = f.id
            LEFT JOIN structure.power_supply_lines psl ON psl.electrical_panelid = fep.electrical_panelid
        ),
        consumers AS (
            SELECT DISTINCT
                   f.feeder_name AS feeder_code,
                   COALESCE(fp.purpose_name, fp.purpose_description) AS power_consumer,
                   fp.purpose_name AS consumer_class,
                   fr.room,
                   NULL::text AS phase1_color,
                   NULL::text AS phase2_color,
                   NULL::text AS phase3_color,
                   f.feeder_name AS data_name
            FROM structure.feeder f
            LEFT JOIN feeder_rooms fr ON fr.feeder_id = f.id
            LEFT JOIN structure.feeder_electrical_panel fep ON fep.feederid = f.id
            LEFT JOIN structure.power_supply_lines psl ON psl.electrical_panelid = fep.electrical_panelid
            LEFT JOIN structure.feeder_purpose fp ON fp.id = psl.feeder_purposeid
        )
    """


def _with_metadata(extra_ctes: str | None = None) -> str:
    ctes = _metadata_ctes()
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
            {_with_metadata()}
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
            {_with_metadata()}
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
            f"{_with_metadata()} SELECT DISTINCT data_name FROM breakers WHERE {' AND '.join(clauses)}",
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

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return FilterSet(where_sql, params, data_names)


def _alias_power_where(where_sql: str, alias: str) -> str:
    return (
        where_sql.replace("data_name", f"{alias}.data_name")
        .replace("timestamp_iso", f"{alias}.timestamp_iso")
    )


def get_filters():
    power_table = _power_table()
    with dashboard_connection() as connection:
        devices = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT data_name, dashboard_label AS label, power_location AS location,
                       power_description AS description, has_breaker_map, has_consumer_map
                FROM devices
                WHERE source_type = 'Power'
                  AND data_name IN (SELECT DISTINCT data_name FROM {power_table})
                ORDER BY dashboard_label
                """
            ).fetchall()
        )
        rooms = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT room, COUNT(DISTINCT data_name) AS device_count
                FROM (
                    SELECT room, data_name FROM consumers WHERE room IS NOT NULL AND room != ''
                    UNION ALL
                    SELECT room, data_name FROM breakers WHERE room IS NOT NULL AND room != ''
                ) room_sources
                WHERE data_name IN (SELECT DISTINCT data_name FROM {power_table})
                GROUP BY room
                ORDER BY room
                """
            ).fetchall()
        )
        consumer_classes = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT consumer_class, COUNT(*) AS consumer_count
                FROM consumers
                WHERE consumer_class IS NOT NULL AND consumer_class != ''
                  AND data_name IN (SELECT DISTINCT data_name FROM {power_table})
                GROUP BY consumer_class
                ORDER BY consumer_class
                """
            ).fetchall()
        )
        buildings = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT building, COUNT(DISTINCT data_name) AS device_count
                FROM breakers
                WHERE building IS NOT NULL AND building != ''
                  AND data_name IN (SELECT DISTINCT data_name FROM {power_table})
                GROUP BY building
                ORDER BY building
                """
            ).fetchall()
        )
        floors = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT floor, COUNT(DISTINCT data_name) AS device_count
                FROM breakers
                WHERE floor IS NOT NULL AND floor != ''
                  AND data_name IN (SELECT DISTINCT data_name FROM {power_table})
                GROUP BY floor
                ORDER BY floor
                """
            ).fetchall()
        )
        locations = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT power_location AS location, COUNT(*) AS device_count
                FROM devices
                WHERE power_location IS NOT NULL AND power_location != ''
                  AND data_name IN (SELECT DISTINCT data_name FROM {power_table})
                GROUP BY power_location
                ORDER BY power_location
                """
            ).fetchall()
        )
        date_range = row_to_dict(
            connection.execute(
                f"""
                SELECT MIN(timestamp_iso) AS date_from, MAX(timestamp_iso) AS date_to
                FROM {power_table}
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
    power_table = _power_table()
    with dashboard_connection() as connection:
        filters = _build_power_filters(connection, request)
        row = row_to_dict(
            connection.execute(
                f"""
                SELECT COUNT(*) AS points,
                       COUNT(DISTINCT data_name) AS devices_count,
                       MIN(timestamp_iso) AS date_from,
                       MAX(timestamp_iso) AS date_to,
                       SUM(energy_kwh_est) AS total_energy_kwh,
                       AVG(active_power_w_avg) / 1000.0 AS avg_power_kw,
                       MAX(active_power_w_max) / 1000.0 AS max_power_kw,
                       AVG(voltage_avg_v) AS avg_voltage_v,
                       AVG(frequency_hz_avg) AS avg_frequency_hz
                FROM {power_table}
                {filters.where_sql}
                """,
                filters.params,
            ).fetchone()
        )
        latest = row_to_dict(
            connection.execute(
                f"""
                WITH latest AS (
                    SELECT data_name, MAX(timestamp_iso) AS timestamp_iso
                    FROM {power_table}
                    {filters.where_sql}
                    GROUP BY data_name
                )
                SELECT SUM(p.active_power_w_avg) / 1000.0 AS current_power_kw,
                       MAX(p.timestamp_iso) AS timestamp_iso
                FROM {power_table} p
                JOIN latest l
                  ON p.data_name = l.data_name AND p.timestamp_iso = l.timestamp_iso
                """,
                filters.params,
            ).fetchone()
        )

    return {**row, **latest}


def get_timeseries(request):
    metric = request.query_params.get("metric", "active_power_w_avg")
    if metric not in POWER_METRICS:
        metric = "active_power_w_avg"

    power_table = _power_table()
    with dashboard_connection() as connection:
        filters = _build_power_filters(connection, request)
        aggregation = "SUM" if metric in {"active_power_w_avg", "reactive_power_var_avg", "apparent_power_va_avg"} else "AVG"
        rows = rows_to_dicts(
            connection.execute(
                f"""
                SELECT timestamp_iso AS timestamp,
                       {aggregation}({metric}) AS value
                FROM {power_table}
                {filters.where_sql}
                GROUP BY timestamp_iso
                ORDER BY timestamp_iso
                LIMIT 20000
                """,
                filters.params,
            ).fetchall()
        )

    return {"metric": metric, "points": rows}


def get_top_devices(request, limit=10):
    power_table = _power_table()
    with dashboard_connection() as connection:
        filters = _build_power_filters(connection, request)
        rows = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata()}
                SELECT p.data_name,
                       d.dashboard_label AS label,
                       d.power_location AS location,
                       SUM(p.energy_kwh_est) AS energy_kwh,
                       AVG(p.active_power_w_avg) / 1000.0 AS avg_power_kw,
                       MAX(p.active_power_w_max) / 1000.0 AS max_power_kw
                FROM {power_table} p
                LEFT JOIN devices d ON d.data_name = p.data_name
                {_alias_power_where(filters.where_sql, 'p')}
                GROUP BY p.data_name, d.dashboard_label, d.power_location
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
                f"{_with_metadata()} SELECT * FROM devices WHERE data_name = %s",
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
                {_with_metadata()}
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
                {_with_metadata()}
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
    power_table = _power_table()
    room_devices_cte = """
        room_devices AS (
            SELECT DISTINCT room, data_name
            FROM consumers
            WHERE room IS NOT NULL AND room != ''
            UNION
            SELECT DISTINCT room, data_name
            FROM breakers
            WHERE room IS NOT NULL AND room != ''
        )
    """
    with dashboard_connection() as connection:
        filters = _build_power_filters(connection, request)
        rows = rows_to_dicts(
            connection.execute(
                f"""
                {_with_metadata(room_devices_cte)}
                SELECT rd.room,
                       COUNT(DISTINCT rd.data_name) AS devices_count,
                       SUM(p.energy_kwh_est) AS energy_kwh,
                       AVG(p.active_power_w_avg) / 1000.0 AS avg_power_kw,
                       MAX(p.active_power_w_max) / 1000.0 AS max_power_kw
                FROM room_devices rd
                JOIN {power_table} p ON p.data_name = rd.data_name
                {_alias_power_where(filters.where_sql, 'p')}
                GROUP BY rd.room
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

from django.core.management.base import BaseCommand
from django.db import ProgrammingError
from django.db import connection

from apps.consumption.dashboard_queries import _power_table


class Command(BaseCommand):
    help = "Create indexes required for energy dashboard analytics."

    def handle(self, *args, **options):
        power_table = _power_table()
        statements = [
            f"CREATE INDEX IF NOT EXISTS electricity_sensor_readings_ts_idx ON {power_table} (ts)",
            f"CREATE INDEX IF NOT EXISTS electricity_sensor_readings_sensor_ts_idx ON {power_table} (sensor_name, ts)",
            "CREATE INDEX IF NOT EXISTS sensor_directory_sensor_name_idx ON sensor_directory (sensor_name)",
            "CREATE INDEX IF NOT EXISTS sensor_directory_roomid_idx ON sensor_directory (roomid)",
        ]

        with connection.cursor() as cursor:
            for statement in statements:
                try:
                    cursor.execute(statement)
                except ProgrammingError as error:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped energy dashboard index because the database user has no permission: {error}"
                        )
                    )
                    connection.rollback()

        self.stdout.write(self.style.SUCCESS("Energy dashboard indexes are ready."))

#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def should_run_migrations(argv):
    if os.environ.get("RUN_DJANGO_MIGRATIONS", "0") != "1":
        return False

    command = argv[1] if len(argv) > 1 else ""
    is_runserver = command == "runserver"
    is_reloader_child = os.environ.get("RUN_MAIN") == "true"
    return is_runserver and not is_reloader_child


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        import django
        from django.core.management import call_command, execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    if should_run_migrations(sys.argv):
        # Keep the dev database schema in sync before the autoreloader starts.
        django.setup()
        call_command('migrate', interactive=False)

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()

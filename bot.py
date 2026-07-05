"""Deprecated entry point.

The bot now runs as a Django management command so it can use the ORM:

    python manage.py runbot

This shim keeps `python bot.py` working by delegating to that command.
"""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command

    call_command("runbot")


if __name__ == "__main__":
    sys.exit(main())

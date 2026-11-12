#!/usr/bin/env python
import os
import sys


def main():
    default_settings = "config.settings.production" if os.environ.get("VERCEL") == "1" else "config.settings.development"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

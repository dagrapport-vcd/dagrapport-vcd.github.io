#!/usr/bin/env python3
"""Drukt de N voorgaande werkdagen (Amsterdamse datum, nieuwste eerst) af, een per regel.

Gebruik: python scripts/vorige_werkdagen.py 5
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tijd import ams_nu  # noqa: E402


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    dag = ams_nu().date()
    gevonden = 0
    while gevonden < n:
        dag -= timedelta(days=1)
        if dag.weekday() < 5:
            print(dag.isoformat())
            gevonden += 1


if __name__ == '__main__':
    main()

#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
python3 -c 'import sqlite3, sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"; print("SQLite", sqlite3.sqlite_version)'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check

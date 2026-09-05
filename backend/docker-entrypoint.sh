#!/bin/sh
set -e

# Demo data seeding is handled automatically by the app's startup event
# (see main.py's _seed_demo_data_on_startup) -- no need to run it here.
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"

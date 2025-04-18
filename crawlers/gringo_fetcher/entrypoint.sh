#!/bin/bash
set -e

echo "[ENTRYPOINT][$(date --iso-8601=seconds)] Gringo Fetcher starting…"
exec python -u fetcher.py

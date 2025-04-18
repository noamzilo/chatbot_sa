#!/bin/bash
set -e

echo "[ENTRYPOINT][$(date --iso-8601=seconds)] Gringo Parser starting…"
exec python -u parser.py

#!/bin/bash

set -e

echo "[ENTRYPOINT] Starting Gringo crawler…"
exec python -u crawler.py

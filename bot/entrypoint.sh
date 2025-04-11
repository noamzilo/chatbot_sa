#!/bin/bash
set -e

# Start the SSH service (for debugging etc.)
service ssh start

# Defer to Python's main.py, which checks WEBHOOK_MODE
exec poetry run python main.py

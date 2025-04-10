#!/bin/bash

# Start the SSH service
service ssh start

# Start the FastAPI server
exec poetry run uvicorn main:app --host 0.0.0.0 --port 8000

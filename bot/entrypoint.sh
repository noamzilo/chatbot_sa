#!/bin/bash

# Start the SSH service
service ssh start

# Start the app (FastAPI/uvicorn or whatever your main command is)
exec poetry run python -m chatbot_sa.telegram_bot

#!/bin/bash

# Start the SSH service
service ssh start

# Start the bot directly
exec poetry run python telegram_bot/bot.py

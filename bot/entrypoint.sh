#!/bin/bash

# Start the SSH service
service ssh start

# Start the bot directly
exec poetry run python main.py

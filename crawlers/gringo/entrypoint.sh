#!/bin/bash

# Run the crawler in a loop
while true; do
    echo "Starting crawler..."
    python crawler.py
    echo "Crawler finished. Waiting 1 hour before next run..."
    sleep 3600
done 
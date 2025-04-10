#!/bin/bash

# Load environment variables
set -a
source .secrets/.env
set +a

# Stop and remove existing container
docker stop chatbot_sa_bot 2>/dev/null || true
docker rm chatbot_sa_bot 2>/dev/null || true

# Build and run the container
cd bot && docker build -t chatbot_sa_bot . && cd ..
docker run -d --name chatbot_sa_bot \
  -p 8000:8000 \
  -v ${SSH_KEY_PATH:-/home/noams/.ssh/github_deploy}:/root/.ssh/id_ed25519:ro \
  -e GIT_SSH_COMMAND="ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
  -e TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}" \
  chatbot_sa_bot

# Show logs
docker logs -f chatbot_sa_bot 
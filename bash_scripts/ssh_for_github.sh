#!/bin/bash

# Set environment variables (replace these with your actual values)
export EC2_USER="ubuntu"  # Replace with your actual EC2 user
export EC2_HOST="98.81.122.237"  # Replace with your actual EC2 host
export TELEGRAM_BOT_TOKEN="your-token"  # Replace with your actual token

# Copy the SSH key to the current directory
cp ../creds/aws/chatbot_sa_key.pem key.pem
chmod 600 key.pem

# Run the SSH command
ssh -o StrictHostKeyChecking=no -i key.pem $EC2_USER@$EC2_HOST << 'EOF'
  set -e
  cd ~/chatbot_sa
  echo "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN" > .env
  docker-compose down
  docker-compose up -d --build
EOF

# Clean up
rm key.pem 
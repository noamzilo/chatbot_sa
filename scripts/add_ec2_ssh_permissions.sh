#!/bin/bash

# Source the .env file from the project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
source "$SCRIPT_DIR/../.secrets/.env"

PORT=22

echo "Fetching GitHub Actions IPs..."
GITHUB_IPS=$(curl -s https://api.github.com/meta | jq -r '.actions[]')

for ip in $GITHUB_IPS; do
	echo "Adding $ip to security group $AWS_SECURITY_GROUP_ID for port $PORT..."
	aws ec2 authorize-security-group-ingress \
		--group-id "$AWS_SECURITY_GROUP_ID" \
		--protocol tcp \
		--port "$PORT" \
		--cidr "$ip" 2>/dev/null || echo "  ↳ $ip already added or failed"
done

echo "✅ Done. Your EC2 should now be reachable from GitHub Actions."

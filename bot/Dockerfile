FROM	python:3.12-slim

ENV	POETRY_VERSION=1.1.12

# Install system packages including SSH server
RUN	apt-get update && \
	apt-get install -y curl openssh-server && \
	rm -rf /var/lib/apt/lists/*

# Set up Poetry
RUN	pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Prepare SSH server
RUN	mkdir /var/run/sshd
RUN	sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config

WORKDIR	/bot

# Copy only the Poetry config first for caching
COPY	pyproject.toml	./
RUN	poetry install --no-interaction --no-ansi

# Now copy the rest of the code
COPY	.	.

# Copy entrypoint
RUN	chmod +x /bot/entrypoint.sh

EXPOSE	22

ENTRYPOINT	["/bot/entrypoint.sh"]

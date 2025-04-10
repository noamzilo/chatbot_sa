FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
	openssh-server \
	build-essential \
	curl \
	&& rm -rf /var/lib/apt/lists/*

# Create SSH directory and set a password for root (for testing only)
RUN mkdir /var/run/sshd && echo 'root:root' | chpasswd
RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config

# Set up Poetry and manually install `six` before using Poetry
ENV POETRY_VERSION=1.1.12
RUN pip install --no-cache-dir six "poetry==$POETRY_VERSION"

WORKDIR /app

# Copy poetry files and install dependencies
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-ansi

# Copy the rest of the app
COPY . .

# Copy the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose SSH port
EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]

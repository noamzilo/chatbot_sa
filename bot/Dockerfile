FROM python:3.12-slim

# Install dependencies including SSH server
RUN apt-get update && apt-get install -y \
	openssh-server \
	build-essential \
	curl \
	&& rm -rf /var/lib/apt/lists/*

# Create SSH directory and set a password for root (optional for debugging, should be disabled in prod)
RUN mkdir /var/run/sshd && \
	echo 'root:root' | chpasswd

# Allow root login over SSH (optional and insecure for production, use with caution)
RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config

# Install latest Poetry (2.1.x) using the official recommended installer
RUN curl -sSL https://install.python-poetry.org | python3 -

# Ensure poetry is in PATH
ENV PATH="/root/.local/bin:$PATH"

# Set workdir
WORKDIR /app

# Copy poetry files and install dependencies
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root

# Copy the rest of the app
COPY . .

# Copy the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose SSH port
EXPOSE 22

# Use the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

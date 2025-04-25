FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y gcc python3-dev postgresql-client && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install poetry

# Copy and install Python dependencies
COPY pyproject.toml ./
RUN poetry config virtualenvs.create false \
	&& poetry install --no-interaction --no-ansi --no-root

# Copy the rest of the application
COPY . .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

# Use the entrypoint script
ENTRYPOINT ["./entrypoint.sh"] 
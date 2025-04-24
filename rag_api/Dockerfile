FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
	postgresql-client \
	&& rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

# Use the entrypoint script
ENTRYPOINT ["./entrypoint.sh"] 
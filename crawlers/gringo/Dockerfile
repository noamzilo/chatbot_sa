FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
	gcc \
	python3-dev \
	&& rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Copy project files
COPY pyproject.toml ./

# Install dependencies
RUN poetry config virtualenvs.create false \
	&& poetry install --no-interaction --no-ansi

# Copy the crawler code
COPY crawler.py ./

# Run the crawler
CMD ["python", "crawler.py"]

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc python3-dev && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

COPY pyproject.toml ./
RUN poetry config virtualenvs.create false \
	&& poetry install --no-interaction --no-ansi --no-root

COPY fetcher.py ./
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

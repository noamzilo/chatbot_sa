# ──────────────────────────────────────────────────────────
#  Gringo Fetcher Dockerfile  (build-time sitemap fallback)
# ──────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# ---------- system deps ----------
RUN apt-get update \
	&& apt-get install -y gcc python3-dev \
	&& rm -rf /var/lib/apt/lists/*

# ---------- poetry + Python deps ----------
RUN pip install --no-cache-dir poetry
COPY pyproject.toml ./
RUN poetry config virtualenvs.create false \
	&& poetry install --no-interaction --no-ansi --no-root

# ---------- project files ----------
COPY fetcher.py ./
COPY entrypoint.sh /entrypoint.sh
RUN  chmod +x /entrypoint.sh

# ---------- build-time sitemap (injected by CI) ----------
ARG  SITEMAP_XML=sitemap.xml          # must exist in build context
COPY ${SITEMAP_XML} /app/sitemap_cached.xml
ENV  SITEMAP_CACHED=/app/sitemap_cached.xml

# ---------- default User-Agent ----------
ENV  USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

ENTRYPOINT ["/entrypoint.sh"]

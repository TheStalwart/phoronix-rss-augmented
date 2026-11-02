FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY phoronix-rss-augmented.py .
COPY docker/phoronix.cron /usr/local/share/phoronix.cron
COPY docker/entrypoint.sh /usr/local/bin/container-entrypoint

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /app/cache /app/output \
    && chown app:app /app/cache /app/output \
    && chmod 0755 /usr/local/bin/container-entrypoint

ENTRYPOINT ["/usr/local/bin/container-entrypoint"]

# Phoronix RSS Augmented

Injects full content of [Phoronix](https://www.phoronix.com/) news articles into RSS feed.

Production instance: <https://phoronix.retromultiplayer.com/phoronix-rss-augmented.xml>

## Runtime requirements

- Python 3.9

## Sentry.io SDK integration

To enable [Sentry.io SDK](https://docs.sentry.io/platforms/python/),
create `sentry.dsn` file with Client Key (DSN) in the root of the project.

## Development environment

### venv-based

To create venv:
`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

To run:
`.venv/bin/python3 phoronix-rss-augmented.py`

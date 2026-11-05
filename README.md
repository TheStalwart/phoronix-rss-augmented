# Phoronix RSS Augmented

Injects full content of [Phoronix](https://www.phoronix.com/) news articles into RSS feed.

- Production page: <https://phoronix.retromultiplayer.com/>
- Production feed: <https://phoronix.retromultiplayer.com/phoronix-rss-augmented.xml>

## Runtime requirements

- Python 3.9

## Sentry.io SDK integration

To enable [Sentry.io SDK](https://docs.sentry.io/platforms/python/),
create `sentry.dsn` file with Client Key (DSN) in the root of the project.

## Better Stack heartbeat monitor

To enable [Better Stack heartbeat monitor](https://betterstack.com/docs/uptime/cron-and-heartbeat-monitor/),
create `heartbeat.url` file with heartbeat URL in the root of the project.

## SolarWinds Loggly integration

Copy `loggly.conf.example` to `loggly.conf` and fill in the TOKEN value.

## New Relic integration

Copy `newrelic.ini` to the root of the project.

## systemd files

`systemd/*` folder contains files that can be copied to `/etc/systemd/system/`
or symlinked with `systemctl link /home/phoronix/phoronix-rss-augmented/systemd/phoronix.*`

Enable cronjob with `systemctl enable --now phoronix.timer`

To uninstall the timer and service:

```sh
sudo systemctl disable --now phoronix.timer
sudo systemctl stop phoronix.service
sudo rm /etc/systemd/system/phoronix.timer /etc/systemd/system/phoronix.service
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

This removes the installed unit files or symlinks, not the originals in this
repository. Stopping the service also stops a run that is currently in progress.

## Container deployment

The container runs the refresh using cron at 45 minutes past every hour,
matching `systemd/phoronix.timer`.
The job runs as UID/GID `1000`;
cron runs as root only to launch the job as that unprivileged user.
No web server is included.

The Compose file persists `cache` and `output` on the host.
Create those directories and make them writable by UID/GID `1000`
before starting the container.
For example, on TrueNAS:

```sh
mkdir -p /mnt/tank/apps/phoronix/cache /mnt/tank/apps/phoronix/output
chown -R 1000:1000 /mnt/tank/apps/phoronix
```

Set `PHORONIX_CACHE_DIR` and `PHORONIX_OUTPUT_DIR` to those host paths
in the TrueNAS app's Compose environment.
Caddy can mount the same output directory read-only
and serve the entire `output` directory.
It contains the landing page, augmented RSS feed,
and the upstream RSS snapshot used for the comparison.
Caddy can serve that directory as a static site;
the app itself does not run a web server.

To build and publish a multi-platform image to Docker Hub,
replace `<dockerhub-user>` with your account:

```sh
docker login
docker buildx build --platform linux/amd64,linux/arm64 \
  --tag <dockerhub-user>/phoronix-rss-augmented:latest --push .
```

### Automatic publishing with GitHub Actions

The `Publish Docker image` workflow builds and publishes
`linux/amd64` and `linux/arm64` images
on every push to `main` or `master`.
Add these Actions secrets in the repository settings:

- `DOCKERHUB_USERNAME`: Docker Hub username
- `DOCKERHUB_TOKEN`: Docker Hub access token with permission to push images

Each successful run updates the `latest` tag
and publishes an immutable tag for that commit's full SHA.

Set `PHORONIX_IMAGE`
to `<dockerhub-user>/phoronix-rss-augmented:latest` in TrueNAS.
In the Compose configuration, keep the `cache` and `output` bind mounts
and set their host paths as above.
The default cron schedule is in `docker/phoronix.cron`; to change it,
set `PHORONIX_CRONTAB_FILE` to the host path of your schedule file.
It is mounted read-only at `/config/phoronix.cron`
and installed with the permissions cron requires.
The default relative path works when deploying from a checkout;
otherwise, copy `docker/phoronix.cron` to a host dataset
and set `PHORONIX_CRONTAB_FILE` to its absolute path.
Keep the cron.d format (including the `root` user field).

Optional integration files
(`sentry.dsn`, `heartbeat.url`, `loggly.conf`, and `newrelic.ini`)
can be mounted read-only at the same paths under `/app`.

## Development environment

### venv-based

To create venv:
`python3 -m venv .venv && .venv/bin/pip install --upgrade --upgrade-strategy eager -r requirements.txt`

To run:
`.venv/bin/python3 phoronix-rss-augmented.py`

After a successful run, `output/` contains
`index.html`, `phoronix-rss-augmented.xml`, and `source_rss.xml`.

#!/bin/sh
set -eu

cron_file=/usr/local/share/phoronix.cron
if [ -r /config/phoronix.cron ]; then
    cron_file=/config/phoronix.cron
fi

# Besides the convenience of seeing the cron configuration in the logs,
# this also serves as a workaround for TrueNAS WebUI
# displaying an endless spinner when a container starts with no output.
printf 'Loaded cron configuration from %s:\n' "$cron_file"
cat "$cron_file"

install -o root -g root -m 0644 "$cron_file" /etc/cron.d/phoronix
exec cron -f

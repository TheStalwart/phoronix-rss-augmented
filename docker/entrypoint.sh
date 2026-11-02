#!/bin/sh
set -eu

cron_file=/usr/local/share/phoronix.cron
if [ -r /config/phoronix.cron ]; then
    cron_file=/config/phoronix.cron
fi

install -o root -g root -m 0644 "$cron_file" /etc/cron.d/phoronix
exec cron -f

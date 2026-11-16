#!/bin/sh
set -eu
cat /etc/radiance/radiance.yaml > /data/radiance.yaml
if [ -f /models/radiance/fine-tunes.yaml ]; then
    cat /models/radiance/fine-tunes.yaml >> /data/radiance.yaml
fi
exec radiance --config /data/radiance.yaml

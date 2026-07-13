# Only exists for slab deploys (slab builds Dockerfiles; docker-compose mounts
# the config instead). Same pinned version as docker-compose.yml.
FROM savonet/liquidsoap:v2.2.5
COPY radio.liq /etc/liquidsoap/radio.liq
CMD ["liquidsoap", "/etc/liquidsoap/radio.liq"]

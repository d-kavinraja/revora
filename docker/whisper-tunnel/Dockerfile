# Private Whisper connectivity for the Revora Docker stack.
# This container terminates the Instabox port-forward inside the private
# Compose network. It publishes no host port: only Revora services on the
# same network can reach 18010.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    openssh-client \
    util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g --no-fund --no-audit instabox@0.8.394 \
    && npm cache clean --force

ENV HOME=/tmp/instabox-home \
    INSTABOX_NO_TELEMETRY=1 \
    WHISPER_TUNNEL_REMOTE=server-2 \
    WHISPER_TUNNEL_LOCAL_PORT=18010 \
    WHISPER_TUNNEL_REMOTE_PORT=8010

RUN mkdir -p /tmp/instabox-home && chown node:node /tmp/instabox-home

WORKDIR /app
COPY entrypoint.sh /usr/local/bin/whisper-tunnel-entrypoint
RUN chmod 0755 /usr/local/bin/whisper-tunnel-entrypoint

USER node
ENTRYPOINT ["/usr/local/bin/whisper-tunnel-entrypoint"]

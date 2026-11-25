# Docker Whisper connectivity

The Docker stack runs the private tunnel as a dedicated Compose service. It
is the container equivalent of the Windows supervisor:

```
backend container -> whisper-tunnel:18010 -> Instabox forward
                  -> server-2 loopback Whisper :8010
```

`whisper-tunnel` publishes no host port. Only containers on the Compose
network can reach it, and the Whisper service still requires its bearer
token. Do not add a `ports:` entry.

## Credentials

Use an Instabox API key. Put it in a file outside Git:

```bash
mkdir -p .secrets
printf '%s' 'ibk_your_key' > .secrets/instabox_api_key
chmod 600 .secrets/instabox_api_key
```

`.secrets/` is ignored by Git. The Compose service mounts that directory
read-only at `/run/secrets`; the entrypoint reads
`/run/secrets/instabox_api_key` without printing it. To use another host
directory, set `INSTABOX_SECRETS_DIR` in the Compose environment. Alternatively
set `INSTABOX_API_KEY`, but the file is preferred because it does not appear in
`docker inspect`.

Set the speech settings for the backend in the same environment or `.env`.
For production Compose:

```bash
REVORA_SPEECH_ENABLED=true
REVORA_SPEECH_TOKEN=the_bearer_token_from_the_private_service
```

The Compose file supplies `REVORA_SPEECH_BASE_URL=http://whisper-tunnel:18010`;
never point the container at `127.0.0.1`, which would mean the backend
container itself.

## Start and status

Production:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 whisper-tunnel
```

Development Compose uses the same service:

```bash
docker compose up -d --build
```

Check the tunnel path without sending the speech token:

```bash
docker compose -f docker-compose.prod.yml exec whisper-tunnel \
  curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18010/health
```

`401` means the forward reached the authenticated remote service. Then check
Admin -> Speech; it remains the authoritative readiness signal. A `200` or
`401` here does not mean the model is ready.

## Automatic recovery

- The entrypoint supervises the Instabox process. It probes the real health
  path, recycles after two failed probes, and uses a bounded 2-60 second
  backoff if the upstream is unavailable.
- It starts the forward with `setsid` and terminates the entire process group
  when recycling. If only the parent node process dies, the descendant `ssh`
  cannot keep port 18010 bound and mask the failure.
- Compose uses `restart: unless-stopped`, so a crashed container, Docker
  daemon restart, or host reboot starts it again once Docker starts.
- Restarting only the backend does not affect the tunnel; the backend health
  check recovers as soon as the tunnel is reachable. No manual tunnel start is
  needed.
- If credentials are missing, the service idles and speech fails closed until
  a key is provided. It does not crash-loop or expose a public endpoint.

## Recovery tests

With the service healthy, the following simulates loss of the upstream
process while the container stays alive:

```bash
docker compose -f docker-compose.prod.yml exec whisper-tunnel sh -c \
  'for p in /proc/[0-9]*; do readlink $p/exe 2>/dev/null | grep -q "/node$" && grep -q instabox $p/cmdline && kill -9 $(basename $p); done'
docker compose -f docker-compose.prod.yml logs --tail=20 whisper-tunnel
docker compose -f docker-compose.prod.yml exec whisper-tunnel \
  curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18010/health
```

The log should show `tunnel is unavailable; recycling it`, then a new
`starting private forward`, then `tunnel is healthy`; the final code should be
`401`. A container-level restart can be tested by killing PID 1; Compose's
restart policy starts a fresh container. A manual `docker stop` or
`docker kill` is an intentional stop and is not automatically restarted.

## Stop

```bash
docker compose -f docker-compose.prod.yml stop whisper-tunnel
docker compose -f docker-compose.prod.yml rm -f whisper-tunnel
```

Stopping the tunnel leaves the backend running; voice requests then fail
closed with the existing speech error. It does not affect text chat or any
other backend feature.

## Security and boundaries

- No `ports:` entry on `whisper-tunnel`; it is reachable only on the Compose
  network.
- Read-only root filesystem, `tmpfs /tmp`, `cap_drop: ALL`, and
  `no-new-privileges`.
- The API key is read from a read-only mount and is never printed. The
  speech bearer token is read by the backend, not this service.
- The service binds `0.0.0.0:18010` only inside its own network namespace;
  Docker publishes no host port.
- It does not start, stop, or modify server-2 Whisper, Ollama, kLLM, or other
  Instabox machines.

## Limitations

- A host reboot requires Docker itself to start. The Compose restart policy
  recovers the tunnel only after the Docker daemon is available.
- An intentionally stopped container stays stopped until `up` is run again.
- The health probe proves network/auth reachability, not model readiness;
  Admin -> Speech remains authoritative.

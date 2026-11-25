# Local Whisper tunnel (development)

Revora's browser voice input uses this local path:

```
Browser -> Next.js :3000 -> FastAPI 127.0.0.1:8000
        -> managed private tunnel 127.0.0.1:18010
        -> server-2 loopback Whisper :8010
```

The tunnel is a development component only. The production backend never starts it, and it must not bind a public address.

## Start, status, stop

Run these commands from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-whisper-tunnel.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-whisper-tunnel.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-whisper-tunnel.ps1 restart
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-whisper-tunnel.ps1 stop
```

`run.bat` calls `start` before it launches the backend and frontend. `start` launches a detached supervisor, not just a one-shot tunnel. `stop.bat` stops the supervisor and its tunnel cleanly; close the backend and frontend terminal windows separately.

`status` also accepts `-Json` for scripts. It reports the supervisor PID, tunnel PID, listener owner, whether the real local HTTP path answered, the restart count, and the last supervisor error.

## Automatic recovery

The supervisor is the long-lived process. It starts the tunnel, checks the listener and the real `/health` round trip, and repairs the path when either is lost:

- If the tunnel process exits, the supervisor starts a new one.
- If only the parent launcher is killed, the descendant `ssh` can keep the port bound. The supervisor verifies the listener's command ancestry, stops that orphaned tunnel tree, and then starts a clean tunnel.
- If the local listener or HTTP round trip fails twice, the supervisor recycles the verified tunnel tree.
- Failed starts back off from 2 seconds up to a 60-second cap, so an unreachable server does not create an uncontrolled restart loop.
- A second `start` is idempotent. The supervisor holds a named mutex and verifies command lines before it kills anything.
- If some other process owns port 18010 and its ancestry does not match the managed tunnel command, the supervisor refuses to duplicate it or kill it. Inspect that owner.

The probe is an unauthenticated `GET /health`; the private service answers `401`, which proves the path reaches the remote application without reading or sending the speech token. The backend's admin Speech health check remains the authoritative readiness signal, so a model that is not ready still fails closed.

## Recovery steps

1. Run `status`. `running` means the supervisor, tunnel, listener, and HTTP path agree.
2. If it reports `supervising/degraded`, wait for the next bounded retry and read the supervisor log.
3. If it is stopped, run `start`. If another process owns the port, inspect that owner; do not kill the Revora backend or frontend.
4. Open the admin Speech page. It polls every 15 seconds and should show Live, Reachable: Yes, Ready: Yes after the tunnel returns.

State and logs are outside the repository:

```
%LOCALAPPDATA%\Revora\dev\whisper-supervisor.pid
%LOCALAPPDATA%\Revora\dev\whisper-supervisor.state.json
%LOCALAPPDATA%\Revora\dev\whisper-supervisor.log
%LOCALAPPDATA%\Revora\dev\whisper-tunnel.pid
%LOCALAPPDATA%\Revora\dev\whisper-tunnel.out.log
%LOCALAPPDATA%\Revora\dev\whisper-tunnel.err.log
```

Run the integration checks with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-dev-whisper-tunnel.ps1
```

The checks start the supervisor, verify idempotent start, deliberately kill the whole tunnel tree, deliberately kill only the parent launcher so the supervisor must clean up an orphaned child, stop it cleanly, and start it again.

## Security and boundaries

- The listener is only `127.0.0.1:18010`; the script never binds `0.0.0.0` or exposes a public port.
- The service token stays in `backend/.env`. The supervisor does not read, print, or store it.
- Audio is uploaded to the backend and forwarded in memory. Revora does not persist audio or transcripts.
- The local supervisor is not added to the production backend or to a production service definition.
- Do not run local Whisper inference or download the model as part of local development.

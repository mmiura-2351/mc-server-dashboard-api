# Daemon Architecture Migration Guide

> Resolves [#61](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/61).
> Retroactive migration guide for the daemon process architecture
> introduced by [PR #60](https://github.com/mmiura-2351/mc-server-dashboard-api/pull/60)
> (merged as `81585f0`, _"feat: Comprehensive server process persistence,
> RCON system, and security enhancements"_).

This document is the **single source of truth for upgrading any deployment
that was provisioned before PR #60 was merged**. It enumerates every
breaking change, the order to apply them, and the verification + rollback
steps. For the architectural background (why daemons, how double-fork
works, monitoring loops, etc.) read
[`docs/DAEMON_PROCESS_ARCHITECTURE.md`](DAEMON_PROCESS_ARCHITECTURE.md).
For configuration field reference see
[`docs/CONFIGURATION.md`](CONFIGURATION.md).

---

## 1. Who must read this

You must follow this guide if **any** of the following is true:

- Your production / staging deployment was first provisioned, or last
  upgraded, from a commit **before** `81585f0` (PR #60).
- You have Minecraft server directories under `./servers/<id>/` that were
  ever started by the pre-#60 code path (i.e. by the legacy
  `asyncio.subprocess`-based runner).
- Your `.env` file does not yet reference any `DAEMON_*` variable and you
  want to opt into (or out of) the new defaults explicitly.

You can skip this guide if you are deploying a clean install from
`master` at or after `81585f0` — in that case the defaults documented in
[`docs/CONFIGURATION.md`](CONFIGURATION.md) §3 apply automatically and
no migration work is required.

---

## 2. What changed at a glance

| Aspect                       | Pre-#60 behaviour                                  | Post-#60 behaviour                                            |
|------------------------------|----------------------------------------------------|---------------------------------------------------------------|
| Process model                | `asyncio.create_subprocess_exec` child of API      | Detached daemon via Unix double-fork (re-parented to PID 1)   |
| Server lifecycle vs API      | Servers killed when API process exits              | Servers **persist** across API restarts                        |
| PID tracking                 | In-memory only (`MinecraftServerManager.processes`)| `{server_dir}/server.pid` JSON file on disk                   |
| Log capture                  | Read from `proc.stdout` pipe                       | Tail-follow `{server_dir}/server.log` file                    |
| Crash recovery on API start  | Stale DB rows; no reconciliation                   | Auto-sync (PID file ⇄ `psutil` ⇄ DB) at lifespan startup      |
| Real-time commands           | None / start-time-only                             | RCON connection per server, auto-enabled, auto-passworded     |
| `server.properties`          | Operator-managed only                              | API rewrites `enable-rcon`, `rcon.port`, `rcon.password`      |
| Default shutdown semantics   | All servers terminated                             | `KEEP_SERVERS_ON_SHUTDOWN=True` keeps them running            |
| Default startup semantics    | No scan                                            | `AUTO_SYNC_ON_STARTUP=True` rehydrates from PID files          |
| New config surface           | 0 `DAEMON_*` env vars                              | 23 `DAEMON_*` env vars (see §3.2)                              |
| Platform                     | Worked on Linux + macOS + WSL (best-effort Win.)   | **Unix-only** (uses `os.fork`, `os.setsid`, see §8)            |

---

## 3. Breaking changes

The changes are grouped along four axes: **process behaviour**,
**configuration**, **filesystem**, and **RCON / network**.

### 3.1 Process behaviour

#### `KEEP_SERVERS_ON_SHUTDOWN` defaults to `True`

When the API shuts down (SIGTERM, systemd stop, `Ctrl-C`), it **no
longer** stops the managed Minecraft servers. The daemons continue
running and are re-attached on next startup.

- Source: `app/main.py:354`, `app/servers/application/minecraft_server.py:2071`.
- Implication: deploy scripts that previously relied on
  _"`systemctl stop mc-dashboard` ⇒ servers stop"_ will now leave the
  servers running. To restore the legacy behaviour set
  `KEEP_SERVERS_ON_SHUTDOWN=False` explicitly in `.env`.
- Per-environment overlay (see [`CONFIGURATION.md`](CONFIGURATION.md) §3):
  development / staging / production default to `True`; only `testing`
  defaults to `False`.

#### `AUTO_SYNC_ON_STARTUP` defaults to `True`

On every API startup, `MinecraftServerManager.discover_running_servers`
scans `servers/<id>/server.pid`, verifies each PID via `psutil`, and
updates the database `Server.status` column to reflect actual state.

- Source: `app/servers/application/minecraft_server.py:639`.
- Implication: stale `RUNNING` rows from crashes will be corrected
  to `STOPPED`; previously-detached daemons will be re-tracked.
- To opt out (legacy behaviour) set `AUTO_SYNC_ON_STARTUP=False`.

#### Double-fork daemonisation

`_create_daemon_process` (`app/servers/application/minecraft_server.py:158`)
replaces the legacy `asyncio` subprocess path. The Java process is now:

- Detached from the API's controlling terminal (`os.setsid()`).
- Re-parented to PID 1 via the canonical double-fork.
- Started with `stdin=/dev/null`, `stdout`/`stderr` redirected to
  `server.log` and `server_error.log` inside the server directory.
- Decoupled file-descriptor-wise (all inherited FDs above 3 are
  closed).

The legacy `_create_daemon_process_alternative` (`subprocess.Popen` with
`start_new_session=True`) is retained as a fallback but is **not** wire-
compatible with old `asyncio`-tracked processes from pre-#60.

### 3.2 Configuration

#### New `DAEMON_*` environment variables

23 new `DAEMON_*` variables now exist on
`app.core.daemon_config.DaemonConfig`, grouped into process creation,
monitoring, resource limits (`DaemonProcessLimits`), logging, security,
RCON, and recovery. The full table — env var name, `DaemonConfig` field,
default, validator, and cross-field constraints — lives in
[`CONFIGURATION.md` § "Daemon process settings"](CONFIGURATION.md#daemon-process-settings-daemon_).

The most consequential cross-field rules to know during upgrade:

- `enable_auto_recovery=true` requires `enable_process_persistence=true`
  **and** `enable_process_monitoring=true`.
- `process_startup_timeout_seconds ≥ monitoring_interval_seconds`.
- `resource_limits.timeout_seconds ≥ process_startup_timeout_seconds`.

#### New top-level `Settings` env vars

These live on `app.core.config.Settings` rather than `DaemonConfig`:

| Env var                     | Default (dev/staging/prod) | Default (testing) |
|-----------------------------|----------------------------|--------------------|
| `KEEP_SERVERS_ON_SHUTDOWN`  | `True`                     | `False`            |
| `AUTO_SYNC_ON_STARTUP`      | `True`                     | `False`            |

See [`CONFIGURATION.md`](CONFIGURATION.md) §3 for the full per-env overlay.

### 3.3 Filesystem

#### `server.pid` JSON file per server

Each running server materialises `{server_dir}/server.pid` (note: the
filename is `server.pid`, **not** `minecraft_server.pid` — earlier docs
were inaccurate). The contents are JSON:

```json
{
    "pid": 12345,
    "server_id": 1,
    "port": 25565,
    "cmd": ["java", "-Xmx1024M", "-jar", "server.jar"],
    "rcon_port": 25575,
    "rcon_password": "secure_password",
    "created_at": "2024-01-01T12:00:00Z"
}
```

Source: `app/servers/application/minecraft_server.py:104` (`_get_pid_file_path`)
and `:654` (PID file write).

Operational notes:

- The file is **owned by the API process user**. Backup tooling that
  archives `servers/` must include it; restoring an archive that omits
  `server.pid` will look like all servers are stopped after the next
  startup scan.
- Deleting `server.pid` while the daemon is alive will not kill it; it
  will just orphan the daemon from API tracking. Use `/api/v1/servers/{id}/stop`
  to stop cleanly.

#### Log capture via tail-follow

Because daemons no longer share a pipe with the API, log streaming
reads `{server_dir}/server.log` directly (`_read_server_logs`,
`app/servers/application/minecraft_server.py`). Implications:

- Any external tool that previously tailed the API's stdout for server
  output must switch to tailing `servers/<id>/server.log` (or use the
  WebSocket log endpoint).
- `server_error.log` is a new sibling file; tail it for startup errors.

### 3.4 RCON

#### Auto-enabled RCON + auto-generated password

On server start, the daemon path writes the following lines into
`server.properties` (overwriting any pre-existing value):

- `enable-rcon=true`
- `rcon.port=<allocated port, default 25575 + offset>`
- `rcon.password=<32-byte URL-safe random secret>`

The password is also persisted to `server.pid` so the API can re-connect
after a restart. **Operators who previously disabled RCON for security
reasons must re-evaluate**: PR #60 made RCON a hard runtime dependency
of group OP/whitelist operations (`/op`, `/deop`, `/whitelist reload`).

Mitigations:

- Bind the RCON port to `127.0.0.1` only (firewall the host or set
  `rcon.bind=127.0.0.1` if your Minecraft version supports it).
- Set `DAEMON_ENABLE_RCON=false` to disable RCON; **this disables the
  affected group operations** and they will report errors.

---

## 4. Pre-upgrade checklist

Run through this list **on the live deployment** before pulling the new
code. Skipping any step risks orphaned processes or lost state.

- [ ] Announce maintenance window to players.
- [ ] **Stop every Minecraft server gracefully** via the legacy API
  (`POST /api/v1/servers/{id}/stop`) or directly with `/stop` in the
  console. The pre-#60 `asyncio.subprocess` PIDs cannot be adopted by
  the new daemon manager — they must be stopped before the upgrade.
- [ ] Verify in-game `world` data is consistent (no pending chunks; for
  paranoia, run `/save-all flush` then `/save-off` before `/stop`).
- [ ] `cp -a servers/ servers.bak.$(date +%Y%m%d)` — file-system snapshot.
- [ ] Backup the application DB:
  - SQLite: `cp app.db app.db.bak.$(date +%Y%m%d)`.
  - PostgreSQL/MySQL: `pg_dump` / `mysqldump`.
- [ ] Record the **current deployed git SHA** (e.g. `git rev-parse HEAD`)
  somewhere durable — you will need it for §7 rollback.
- [ ] Note the current `.env` file: in particular any custom `JAVA_*_PATH`
  or `CORS_ORIGINS` you intend to preserve.
- [ ] Verify the host has Java on `PATH` and the API user has permission
  to `fork`, write to `servers/<id>/`, and bind any new RCON ports.

---

## 5. Upgrade steps

1. **Stop the API service.**
   ```bash
   sudo systemctl stop mc-dashboard      # or: just service-stop
   ```
2. **Confirm no Java/Minecraft processes survive.** (They should not —
   you stopped them in §4. If any remain, kill them now or the new code
   will report port conflicts when starting fresh daemons.)
   ```bash
   pgrep -fa 'java .*server\.jar' || echo "clean"
   ```
3. **Pull and install the new code.**
   ```bash
   git fetch origin
   git checkout master      # or your release tag at/after 81585f0
   uv sync
   ```
4. **Review and edit `.env`** for the new variables documented in §3.2.
   At minimum, decide explicitly whether you want
   `KEEP_SERVERS_ON_SHUTDOWN=True` (new default) or `False` (legacy
   behaviour). For production keep the defaults unless you have a
   reason not to.
5. **Apply any pending DB migrations** (the project auto-creates tables
   on startup; nothing extra is required for PR #60 itself).
6. **Start the API service.**
   ```bash
   sudo systemctl start mc-dashboard     # or: just service-start
   ```
7. **Start each server via the API** (`POST /api/v1/servers/{id}/start`).
   The first start will create `server.pid` and rewrite the RCON section
   of `server.properties`. From this point on, restarting the API does
   **not** stop the Minecraft daemons.

---

## 6. Post-upgrade verification

Run all of the following and confirm the expected output.

```bash
# 1. API is up and the lifespan startup completed without raising.
curl -fsS http://localhost:8000/api/v1/health
# Expect: HTTP 200 + JSON status payload (see app/main.py:444 / app/health/api/router.py).

# 2. Daemon process is detached and re-parented to PID 1.
ps -eo pid,ppid,user,args | grep '[s]erver\.jar'
# Expect: PPID = 1 (or the equivalent init/systemd pid on the host).

# 3. PID file exists, contains JSON, and the pid is alive.
cat servers/1/server.pid | python -m json.tool
kill -0 "$(jq -r .pid servers/1/server.pid)" && echo "alive"

# 4. RCON section was written.
grep -E '^(enable-rcon|rcon\.port|rcon\.password)=' servers/1/server.properties
# Expect: enable-rcon=true, rcon.port=<num>, rcon.password=<32+ chars>.

# 5. AUTO_SYNC actually reconciled state. Restart the API and re-check
#    /api/v1/servers/{id} — the status should remain RUNNING without you
#    having to issue another /start.
sudo systemctl restart mc-dashboard
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/servers/1
```

Optional but recommended:

- Tail `servers/<id>/server.log` and confirm new lines arrive in
  real-time (proves the tail-follow path works).
- Trigger an OP group attach/detach and confirm the in-game player is
  op'd / deop'd within ~1 second (proves RCON works end-to-end).

---

## 7. Rollback

If the upgrade misbehaves and you need to revert:

1. **Stop the API.**
   ```bash
   sudo systemctl stop mc-dashboard
   ```
2. **Manually kill every daemon** — they will not exit when the API
   exits, and the old code does not know how to adopt them.
   ```bash
   for f in servers/*/server.pid; do
       pid=$(jq -r .pid "$f")
       [ -n "$pid" ] && kill -TERM "$pid"
   done
   # If any survive, escalate:
   pkill -KILL -f 'java .*server\.jar'
   ```
3. **Remove the PID files** so the new code (post-rollback re-upgrade)
   does not try to adopt dead pids.
   ```bash
   rm -f servers/*/server.pid servers/*/server_error.log
   ```
4. **Restore the DB and `servers/` snapshots** from §4 if needed.
5. **Check out the pre-upgrade SHA** you recorded in §4.
   ```bash
   git checkout <pre-upgrade-sha>
   uv sync
   sudo systemctl start mc-dashboard
   ```
6. **Decide on `server.properties` RCON lines**: the new code rewrote
   them. If you want to revert RCON to disabled, edit each
   `servers/<id>/server.properties` manually before restarting.

---

## 8. Platform compatibility

The daemon path uses `os.fork`, `os.setsid`, and `os.umask`, all of
which are Unix-specific.

| Platform                          | Status              | Notes                                                |
|-----------------------------------|---------------------|------------------------------------------------------|
| Linux (glibc, x86_64 / aarch64)   | **Verified**        | All `tests/integration/test_process_persistence.py` cases pass on CI Linux runners. |
| macOS (Intel / Apple Silicon)     | Should work         | Uses the same `os.fork` API; not part of CI matrix. Report issues against #62. |
| Other Unix-likes (BSD, illumos)   | Should work         | Untested. Same caveat as macOS.                      |
| Windows Subsystem for Linux (WSL) | Should work         | Treated as Linux. Native Windows file paths inside WSL not supported. |
| Native Windows (Win32)            | **Not supported**   | `os.fork`, `os.setsid` raise `AttributeError`. Use WSL2. |

Issue [#62](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/62)
tracks formalising this compatibility statement in code (e.g. an early
runtime guard with a clear error message).

---

## 9. Troubleshooting

### Server shows `STOPPED` after API restart even though it is still running

Likely cause: `AUTO_SYNC_ON_STARTUP` is `False` (or set so via overlay),
or `server.pid` was deleted while the daemon was alive.

- Confirm with `pgrep -fa server.jar` that the process is alive.
- Re-create the PID file manually is **not** supported; the safest path
  is to `kill` the orphan and re-issue `POST /api/v1/servers/{id}/start`.
- Set `AUTO_SYNC_ON_STARTUP=true` in `.env` and restart the API.

### `OSError: [Errno 12] Cannot allocate memory` during `fork`

The host is over-committed. The double-fork temporarily duplicates the
API's address space. Either lower the JVM memory of co-located servers,
raise `vm.overcommit_memory`, or add swap.

### RCON commands fail with `Connection refused`

- Verify `enable-rcon=true` in `server.properties`.
- Verify the port from `server.pid`'s `rcon_port` is bound:
  `ss -ltnp | grep <port>`.
- Check `DAEMON_ENABLE_RCON` is not set to `false` in `.env`.

### Logs stop streaming after log rotation

The tail-follow loop handles rotation but races on very rapid rotation
(< 1 cycle of `DAEMON_MONITORING_INTERVAL`). Increase the interval or
the rotation size threshold.

### `PermissionError` writing `server.pid`

The API process user does not own `servers/<id>/`. Fix ownership:
`chown -R mc-dashboard:mc-dashboard servers/`.

---

## 10. References

- Source of truth for daemon internals:
  [`docs/DAEMON_PROCESS_ARCHITECTURE.md`](DAEMON_PROCESS_ARCHITECTURE.md).
- Configuration field reference and per-env overlay:
  [`docs/CONFIGURATION.md`](CONFIGURATION.md).
- RCON details: [`docs/RCON_INTEGRATION.md`](RCON_INTEGRATION.md).
- Code entry points:
  - `app/core/daemon_config.py` (env mapping + validators).
  - `app/servers/application/minecraft_server.py` (`_create_daemon_process`,
    `_get_pid_file_path`, `discover_running_servers`, shutdown loop).
  - `app/main.py` (lifespan startup + `KEEP_SERVERS_ON_SHUTDOWN` branch).
- PR #60 (origin): merge commit `81585f0`.
- Issue #61 (this guide).
- Issue #62 (platform compatibility hardening).

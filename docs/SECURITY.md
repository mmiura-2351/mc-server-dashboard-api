# Security Policies

This document captures the authentication-related security controls
enforced by the API. The policies are configurable via environment
variables (see `.env.example`) so deployments can tighten or relax
them per environment. Production defaults follow OWASP ASVS v4 L1
and NIST 800-63B guidance.

## Password strength (Issue #73, Phase 1A)

### Production defaults

| Control                         | Default                                          | Override                              |
| ------------------------------- | ------------------------------------------------ | ------------------------------------- |
| Minimum length                  | 12 characters                                    | `PASSWORD_MIN_LENGTH`                 |
| Maximum length                  | 128 characters (bcrypt 72-byte cap + DoS guard)  | `PASSWORD_MAX_LENGTH`                 |
| Complexity                      | ≥ 3 of {upper, lower, digit, symbol} **or** ≥ 16 chars | `PASSWORD_REQUIRE_COMPLEXITY`         |
| Common-password blocklist       | SecLists xato-net top-10,000 (MIT/public-domain) | `PASSWORD_CHECK_COMMON_LIST`          |
| Cross-field check               | Reject if password contains the username or e-mail local-part | `PASSWORD_FORBID_USER_INFO`           |
| Simple-pattern guard            | Reject 4+ repeated characters or 4+ alphabet/keyboard/numeric runs | `PASSWORD_FORBID_SIMPLE_PATTERNS`     |
| Policy release date             | 2026-05-23                                       | `PASSWORD_POLICY_RELEASE_DATE`        |

### Where it is enforced

1. **HTTP layer** — `UserCreate.password` / `PasswordUpdate.new_password`
   schemas run a Pydantic `@field_validator` plus a `@model_validator`
   for the username/e-mail cross-field check. Failures surface as
   HTTP 422 with a human-readable reason list.
2. **Application layer** — `UserService.register_user` /
   `UserService.update_password` re-run the policy as defense-in-depth.
   Failures surface as HTTP 400 (`Password does not meet policy: …`).

The policy itself is a framework-pure value object
(`app.users.domain.value_objects.PasswordPolicy`) that can be
exercised in isolation; the runtime instance is built by
`app.users.application.password_policy.get_password_policy()`,
which is cached for the process lifetime and rebuildable via
`reset_password_policy_cache()` (used by tests).

### Grandfathering

The `users.password_set_at` column records when each credential was
last set. Users whose `password_set_at` is `NULL` or older than
`PASSWORD_POLICY_RELEASE_DATE` are *grandfathered*: their login is
accepted, but the response carries

```
X-Password-Policy-Warning: weak-password
```

so the frontend can prompt them to rotate. Forced rotation is
deferred to Phase 2 (out of scope for the Phase 1 PR).

## Brute-force protection (Issue #73, Phase 1B)

### Production defaults

| Control                                  | Default     | Override                                  |
| ---------------------------------------- | ----------- | ----------------------------------------- |
| Enabled                                  | `true`      | `BRUTE_FORCE_ENABLED`                     |
| Username-based threshold                 | 5 failures  | `BRUTE_FORCE_USERNAME_THRESHOLD`          |
| Username sliding-window                  | 900 s       | `BRUTE_FORCE_USERNAME_WINDOW_SECONDS`     |
| Lockout base duration                    | 900 s       | `BRUTE_FORCE_LOCKOUT_BASE_SECONDS`        |
| Lockout cap (exponential back-off)       | 86,400 s    | `BRUTE_FORCE_LOCKOUT_MAX_SECONDS`         |
| IP-based threshold                       | 20 failures | `BRUTE_FORCE_IP_THRESHOLD`                |
| IP sliding-window                        | 300 s       | `BRUTE_FORCE_IP_WINDOW_SECONDS`           |
| IP lockout duration                      | 300 s       | `BRUTE_FORCE_IP_LOCKOUT_SECONDS`          |
| Artificial response delay (anti-timing)  | 200 ms      | `BRUTE_FORCE_DELAY_MS`                    |

### Tables

The `BruteForceService` persists state in two tables:

* `login_attempts` — append-only record of every authentication
  attempt (username, IP, user-agent, success flag, failure reason,
  timestamp). Sliding-window queries count rows in this table.
* `account_lockouts` — at-most-one row per username, recording the
  active lockout (`locked_until`) and the historic `lockout_count`
  that drives exponential back-off.

### Endpoint integration

`POST /api/v1/auth/token`:

1. Run `check_lockout(username, ip)` before authenticating. Locked
   requests return **HTTP 429** with a `Retry-After` header. The
   error body intentionally mirrors the generic credential failure
   so an attacker cannot infer lockout state from the body alone.
2. Authenticate as before.
3. Call `record_attempt(...)` regardless of outcome. A failure that
   crosses the threshold triggers a `security_event` audit log entry
   (`event_type="account_locked"` or `"brute_force_ip_blocked"`).
4. Apply a 200 ms artificial delay on every failure path to deny
   timing-based username enumeration.

### Out of scope (Phase 2/3)

* Refresh-token IP/User-Agent binding (`refresh_tokens.last_used_at` etc.) — Phase 2
* Forced rotation for grandfathered weak passwords — Phase 2
* zxcvbn entropy meter — Phase 2
* MFA (Issue #25) — Phase 3
* CAPTCHA / interactive challenge — Phase 3

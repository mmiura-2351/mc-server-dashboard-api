# Dependency Management Policy

The dependency management policy for `mc-server-dashboard-api`. Drafted under
Issue #150 (parent) / #161 (B-1).

## 1. Version specification style

Direct dependencies in `pyproject.toml` are pinned using one of the following
styles, depending on the kind of package:

| Kind | Form | Example |
|---|---|---|
| **Runtime direct dependency** | `"name>=X.Y.Z,<NEXT_MAJOR"` | `"fastapi[standard]>=0.136,<1.0.0"`, `"SQLAlchemy>=2.0.49,<3.0.0"` |
| **Runtime direct dependency on a `0.x.y` library** | `"name>=X.Y.Z,<X.NEXT_MINOR"` (or wider if upstream commits to no breaks) | `"starlette>=0.47.3,<1.1.0"` |
| **Dev dependency** (lint/test/type/hooks) | `"name>=X.Y.Z"` | `"pytest>=8.4.1"`, `"ruff>=0.11.12"` |
| **Transitive dependency** | not written in `pyproject.toml` | pinned in `uv.lock` |

### Design intent

- **Direct deps cap the next major**: under SemVer this admits minor/patch
  updates while keeping major (breaking) bumps explicit and PR-reviewed.
- **`0.x.y` libraries break on minor bumps**: per SemVer convention, cap at
  `<X.NEXT_MINOR`. Some libraries (e.g. starlette) make stronger guarantees
  inside `0.x` and allow a wider cap — keep the rationale in the diff if so.
- **No upper bound on dev deps**: they do not affect runtime behaviour, and
  staying current with tooling improvements (speed, new features) is cheap.
- **No transitive deps in `pyproject.toml`**: `uv.lock` is the source of
  truth; duplicating in `pyproject.toml` creates dual maintenance.

## 2. Exception: exact pinning (`==`)

Exact pinning (`==`) is permitted only when one of the following applies:

- A security requirement mandates an exact version (cryptographic libraries).
- A known compatibility issue prevents any version other than a specific one.
- The upstream has a documented history of SemVer violations causing breakage
  on patch bumps.

When pinning exactly, add a comment immediately above the line in
`pyproject.toml` explaining the reason and linking the issue/PR/advisory.

```toml
# Pinned: CVE-XXXX-YYYY mitigation requires exact version (Refs: #NNN)
"some-lib==1.2.3",
```

## 3. Dependency grouping

| Group | Location | Contents |
|---|---|---|
| `[project].dependencies` | runtime only | fastapi, pydantic, sqlalchemy, uvicorn, passlib, python-jose, aiohttp, aiofiles, psutil, … |
| `[dependency-groups].dev` | dev / test / lint / type / hooks | pytest, pytest-asyncio, pytest-xdist, httpx (TestClient), ruff, mypy, pre-commit, coverage |

### Classification rule

- Ask: "if this dependency disappears under `uv sync` (production-like
  install), does the app still start and serve requests?"
  - If no → `dependencies`.
  - If yes → `dev` group.
- Test frameworks, linters, type checkers, the TestClient (`httpx`), and
  formatters all belong in the `dev` group.

## 4. Lockfile (`uv.lock`) operations

- **Single source of truth**: `uv.lock` is the entry point for reproducibility.
- Must be committed to `master`.
- Setup:
  - Production-like: `uv sync`
  - Development: `uv sync --group dev`
- Updates:
  - All patch + minor in one go: `uv lock --upgrade`
  - Single package: `uv lock --upgrade-package <name>`

## 5. Security updates

| Kind | Response policy |
|---|---|
| GitHub Security Advisory alert | Open a patch PR within **1 week** of receipt |
| Dependabot security update PR | Triage within **1 business day** |
| Known CVE on a legacy library | Plan staged replacement (tracked under Issue #164 B-4) |
| High-severity vulnerability (RCE, etc.) | Hotfix release outside the normal cadence |

Security work carries the **`dependencies` + `security`** labels.

### 5.1 Supply-chain cooldown policy

To mitigate maintainer-account takeover, typosquatting, and compromised
releases — which can take several days to detect and retract — **do not
adopt any release published within the last 7 days**. Holding a 7-day risk
window absorbs most public-incident timelines.

| Tool | Where it's configured | Behaviour |
|---|---|---|
| `uv` | `pyproject.toml` → `[tool.uv].exclude-newer = "7 days"` | Excludes releases under 7 days old during `uv lock` / `uv lock --upgrade` / `uv add` resolution (`uv sync` honours the lock so it is unaffected) |
| Dependabot | `.github/dependabot.yml` → `cooldown` | Holds new PRs until `default-days` (= 7) have passed; major bumps wait `semver-major-days` (= 14) |

#### Override procedure (urgent CVE response)

If a cooldown bypass is required, use one of the following. Always document
the reason (CVE number, advisory link) in the PR body.

- **uv (local)**: bypass cooldown for a single package.
  `--exclude-newer-package` accepts `PACKAGE=DATE` or `PACKAGE=false`.

  ```bash
  # Disable cooldown entirely and adopt the latest release
  uv lock --upgrade-package <pkg> --exclude-newer-package <pkg>=false

  # Or cap at a specific date (e.g. the CVE advisory publication date)
  uv lock --upgrade-package <pkg> --exclude-newer-package <pkg>=2026-05-15
  ```

- **Dependabot**: security-update PRs that map to a GitHub Security
  Advisory bypass cooldown automatically; no extra config needed. To pull
  one in manually, run the `uv` command above and open the PR yourself.

## 6. Dependabot policy

The current `.github/dependabot.yml` settings codified as policy.

| Item | Setting |
|---|---|
| Package ecosystem | `pip` |
| Schedule | weekly, Monday 21:00 UTC (Tokyo Monday 06:00) |
| Grouping | `production-dependencies` / `dev-dependencies` (two groups) |
| Open PR cap | 2 |
| Commit convention | `chore(deps): ...` (scoped) |
| Auto-applied labels | `dependencies`, `python` |
| Cooldown | `default-days: 7` / `semver-major-days: 14` (see §5.1) |

### Merge policy

| Update kind | Action |
|---|---|
| Patch | Standard review → squash merge |
| Minor | Standard review → squash merge (CI must be green) |
| Major | Dependabot excludes these from the group and opens individual PRs. Review per Issue #164 B-4 |

## 7. Major version updates

Major updates are likely to carry breaking changes; handle them as follows:

1. **Always a standalone PR**: never bundled into a Dependabot group update.
2. **Cite the upstream migration guide**: quote relevant excerpts in the PR body.
3. **If breaking**: coordinate with our project's own breaking-change cadence
   (see Issue #176 — versioning) so the major bumps line up.
4. **Validate**: unit + integration tests plus a smoke test of the affected
   feature area.

## 8. Exceptions and references

- **Vulnerability in a transitive dep**: transitive deps live only in
  `uv.lock`. Pin a temporary direct dependency in `pyproject.toml` to
  override, and remove it once upstream ships a fix.
- **Cases not covered here**: open an issue, discuss, and append the
  conclusion to this document.

## References

- Parent issue: [#150](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/150) — library update policy and bulk update.
- Drafting issue: [#161](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/161) (B-1).
- Related: [#162](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/162) (B-2, unify version specification style); [#164](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/164) (B-4, individual major-update review).
- Related: [#194](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/194) (enforce cooldown policy).

# CLAUDE.md

Standing rules for Claude Code on this repository. Everything else —
architecture, configuration, API surface, dev workflow — lives under
[`docs/README.md`](docs/README.md). Read that first when the user's request
needs context beyond the rules below.

## Rules

### Rule 1 — Promote standing requests into rules

If a user instruction looks like an ongoing requirement (not a one-shot
task), ask once: **"Should I make this a standard rule?"** On yes, add it
here as a new Rule. Apply it from the next turn onward.

A request is "standing" when it starts with words like *always*, *never*,
*from now on*, *whenever*, or describes a convention the user wants future
work to follow.

### Rule 2 — Never commit on red

Before committing, the relevant pre-commit / pre-push hooks must pass. Do
not use `--no-verify` to bypass them; fix the cause instead. If a hook
fails, the commit did not happen — re-stage and create a **new** commit
rather than `--amend`.

Install both hook stages once:
`uv run pre-commit install --hook-type pre-commit --hook-type pre-push`.

### Rule 3 — Add tests by reading code, not by chasing a number

When adding tests for an existing module:

1. Read the module and its current tests first; do not duplicate cases.
2. Cover error paths, permission checks, and edge cases — not only the
   happy path.
3. Check progress with `just coverage` and iterate on the **specific
   uncovered lines**, not on a percentage target.

### Rule 4 — Out-of-scope findings become GitHub issues

While reviewing or implementing, if you spot a bug, missing feature, or
improvement that is out of scope for the current change, open a GitHub
issue rather than expanding the PR.

Each issue must include:

- A concrete file:line reference.
- The problem in one or two sentences.
- A label from `bug` / `enhancement` / `feature-request`.

### Rule 5 — Plan before implementing an issue

When picking up an issue:

1. Create a branch named per Rule 8 and attach it to the issue.
2. Sketch the change (TaskCreate or `EnterPlanMode`) before editing code.
3. If the issue is large, split it into sub-issues first; one branch per
   sub-issue.
4. The PR opened from the branch must close the issue with `Resolves #N`.

### Rule 6 — Pick the right test scope for the situation

| Stage | Scope | Command |
|---|---|---|
| pre-commit hook | unit smoke (`-m "not slow"`) | `pytest tests/unit -m "not slow"` |
| pre-push hook | unit + integration smoke (`-m "not slow"`) | `pytest tests/unit tests/integration -m "not slow"` |
| PR CI (`ci.yaml`) | full suite incl. `slow` | `just test` |
| nightly | full suite + coverage | `just coverage` |

- Manual full-suite run: prefer `just test` over raw `pytest`.
- Mark any test that takes ≥ 1 s or spawns a subprocess with
  `@pytest.mark.slow`. (Policy: [`docs/dev/TESTING.md`](docs/dev/TESTING.md).)
- Pre-push depends on a JRE on `PATH`; push from a machine with Java
  until issue [#209](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/209)
  annotates the affected tests with `@pytest.mark.requires_java`.

### Rule 7 — Close issues only after the change ships

An issue is closed only after the PR that addresses it is merged. The
closing comment must include a one-line summary and the PR/commit ref.

### Rule 8 — Git/GitHub conventions

- **Branches**: `fix/issue-{N}-{slug}` for bugs, `feature/issue-{N}-{slug}`
  for everything else. One issue per branch. If no GitHub issue exists for
  the work, omit the `issue-{N}-` segment and use `fix/{slug}` or
  `feature/{slug}` directly.
- **PR title**: short imperative ("Fix Y", not "Fixed Y" or "Y fix").
- **PR body**: includes `Resolves #N` (or `Fixes` / `Refs`) on its own line
  when a related issue exists; omit when there is none.
- **VCS tool**: per the global guideline, use `bit` instead of `git`. Inside
  a `git worktree`, fall back to `git` directly (bit 0.39.0 ignores
  commondir and corrupts commit/push).

### Rule 9 — PR review hygiene

To inspect a PR thoroughly:

- `gh pr view <N>` — description and metadata (does **not** show the diff
  or inline review comments).
- `gh pr diff <N>` — the actual code changes.
- `gh api repos/{owner}/{repo}/pulls/<N>/comments` — inline review
  comments; `gh pr view --comments` only surfaces the top-level thread, so
  do not rely on it alone.
- `gh pr checkout <N>` when you need to run the branch locally.

Submit reviews with `gh pr review`. Group findings by severity:
`bug` / `improvement` / `question` / `nit`. Each finding links a file:line.
Approve only after every `bug`-severity item is resolved.

### Rule 10 — Squash-merge by default

`gh pr merge <N> --squash --delete-branch`. The squash commit subject is
the PR title; the body is one or two short paragraphs. Avoid rebase- or
merge-commit modes unless the user explicitly asks.

### Rule 11 — English everywhere

Everything text-bearing in this repo is English:

- Every Markdown file (`README.md`, `CLAUDE.md`, `CHANGELOG.md`,
  `docs/**/*.md`, `deployment/**/*.md`, `.github/**/*.md`, etc.).
- PR descriptions and issue templates.
- **Commit messages** (subject + body).
- **Code comments** — `#` comments and docstrings in `.py`, comments in
  `.yml` / `.toml` / `.sh` / `.nix`, etc.

When editing a file that still contains Japanese, translate the touched
section as part of the change rather than leaving mixed languages behind.
Code identifiers (variable, function, class names) follow the existing
language convention of the source — for Python that already means English.

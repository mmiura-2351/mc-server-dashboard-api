# Release Operations Guide

This document defines the versioning conventions and release procedure for
`mc-server-dashboard-api`.
Parent issue: #183 / roadmap: #188 (Phase 3).

## 1. Versioning convention (SemVer)

Versions follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
and are written as `MAJOR.MINOR.PATCH`.

| Part | Meaning | Example |
|---|---|---|
| MAJOR | Backwards-incompatible changes | `1.0.0` → `2.0.0` |
| MINOR | Backwards-compatible new functionality | `1.2.0` → `1.3.0` |
| PATCH | Backwards-compatible bug fixes | `1.2.3` → `1.2.4` |

### 1.1 Conventions during `0.x.y`

Per the SemVer spec, the public API is considered unstable while the version
is `0.x.y`. This project operates as follows during that window:

- **Backwards-incompatible changes**: bump MINOR (`0.1.0` → `0.2.0`).
- **New functionality and compatible bug fixes**: bump PATCH (`0.1.0` → `0.1.1`).
- The timing of reaching `1.0.0` is decided separately (when the API is judged
  stable enough for production use).

### 1.2 Pre-release

Release candidates are tagged as `vX.Y.Z-rc.N` (e.g. `v0.2.0-rc.1`).
Other suffixes (`-alpha.N`, `-beta.N`) are not used by default.

### 1.3 Tag naming convention

- Release tags use `vX.Y.Z` (the leading `v` is required).
- Pre-releases: `vX.Y.Z-rc.N`.
- Anything other than an official release (local verification tags, etc.) must
  not carry the `v` prefix.

## 2. Single source of truth for the version

`pyproject.toml`'s `[project].version` is the single source of truth.

- Python code references `app.__version__` (which internally calls
  `importlib.metadata.version("mc-server-dashboard-api")`).
- The FastAPI app passes `FastAPI(version=__version__)` so the version is
  reflected in the OpenAPI schema.
- Do not hard-code the version number in `README.md` or any other doc.

## 3. CHANGELOG operation

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

### 3.1 At PR-creation time

- User-visible changes — new features, bug fixes, breaking changes, dependency
  updates — are added to the `[Unreleased]` section of `CHANGELOG.md`.
- Changes that do not affect users (internal refactors, CI configuration,
  developer-experience-only changes) may be omitted.

### 3.2 At release time

- Rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and add a new empty
  `[Unreleased]` directly above it.
- The date is the day the release PR is merged, in UTC.

## 4. Release procedure (automated via tagpr)

The repository automates version bumps, tag creation, and GitHub Release
publication using [tagpr](https://github.com/Songmu/tagpr)
(`.github/workflows/tagpr.yml` / `.tagpr`).

### 4.1 Standard release flow

1. **Merge a PR** (the normal development flow).
   - Add user-visible changes to `CHANGELOG.md`'s `[Unreleased]` section.
   - For breaking changes or new functionality, apply a PR label:
     - `tagpr:major` — MAJOR bump.
     - `tagpr:minor` — MINOR bump.
     - No label — PATCH bump (default).
2. **tagpr detects the push to `master`** and automatically creates or updates
   a release PR (example title: `Release for vX.Y.Z`).
   - It rewrites `pyproject.toml`'s `version` to the next version.
   - It runs `uv lock` to sync the lockfile (configured under `.tagpr`'s
     `command` setting).
3. **Tidy the CHANGELOG inside the release PR** (manual, by a maintainer).
   - Rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and add a new
     `[Unreleased]` above it.
   - Commit directly to the release-PR branch and push.
4. **Review the release PR**.
   - Only the `version` line in `pyproject.toml` should be changed.
   - `uv.lock` should be synced.
   - No unrelated changes should be mixed in.
5. **Merge the release PR** (squash merge).
   - After the merge, tagpr automatically creates and pushes the `vX.Y.Z` tag
     and publishes the GitHub Release.

### 4.2 Authentication token (Fine-grained PAT)

So that `ci.yaml` (lint / format / test) runs on the release PRs that tagpr
creates, the workflow uses a **Fine-grained PAT stored as the `TAGPR_PAT`
secret** rather than the default `GITHUB_TOKEN`.

> GitHub's policy is that PRs created with `GITHUB_TOKEN` do not trigger
> other workflows. PRs created with a PAT do.

#### Setup (one-time)

1. Create a Fine-grained PAT at
   https://github.com/settings/personal-access-tokens/new:
   - **Repository access**: "Only select repositories" → this repository only.
   - **Repository permissions**:
     - **Contents**: Read and write (to create commits and tags).
     - **Pull requests**: Read and write (to create and update release PRs).
     - **Metadata**: Read-only (granted automatically).
2. In repository Settings → Secrets and variables → Actions → New repository
   secret:
   - **Name**: `TAGPR_PAT`.
   - **Secret**: the generated PAT.

#### Operational notes

- The PAT is owned by the user who created it. If that user leaves the
  organization or revokes the PAT, tagpr stops working.
- If the PAT has an expiry date, rotate it before it expires.
- Migrating to GitHub App-based authentication in the future would remove
  this single-owner dependency (tracked in a separate issue).

### 4.3 Repository settings (one-time)

For tagpr to be allowed to create PRs, confirm the following setting:

- Settings → Actions → General → Workflow permissions:
  - **Allow GitHub Actions to create and approve pull requests** is enabled.

### 4.4 Handling Dependabot PRs

tagpr excludes Dependabot-created PRs from version-bump consideration by
default. While only dependency updates have landed on `master`, no release PR
is created — meaning dependency updates alone do not cut a new version. To
include dependency updates in a release, either merge one regular
user-visible PR, or land a meaningful commit on `master` after the Dependabot
merges. (Note that tagpr's default behaviour is a patch bump with no label,
so no explicit label is required for the regular case.)

## 5. Manual release procedure (fallback)

When tagpr is unavailable, for the first release, or in exceptional cases,
use this manual procedure.

1. Create a branch `release/vX.Y.Z`.
2. Update `pyproject.toml`'s `version` and re-run `uv lock`.
3. `CHANGELOG.md`: rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and add a
   new `[Unreleased]`.
4. Open a PR (title: `release: vX.Y.Z`); after review, squash merge.
5. Create and push the tag:
   ```bash
   git checkout master && git pull
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```
6. Publish the GitHub Release:
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" \
       --notes-file <(awk '/^## \[X\.Y\.Z\]/{flag=1;next} /^## \[/{flag=0} flag' CHANGELOG.md)
   ```

## 6. Hotfix

For a critical bug in a released version, a hotfix branched from the tag is
also acceptable as an alternative to the normal flow from `master`.

```bash
git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z
# Commit the fix.
# Release via the manual procedure in Section 5 (tagpr's automation does not
# target hotfix workflows).
git checkout master
git merge --no-ff hotfix/vX.Y.Z+1
```

## 7. Out of scope (tracked in future issues)

- Adding a `/version` endpoint.
- Automatic CHANGELOG generation (using tagpr's `changelog = true` feature, or
  generation from PR labels).

"""Domain layer for the templates module.

Contains pure domain entities (`entities.py`), Port (Protocol) definitions
(`ports.py`), and domain exceptions (`exceptions.py`). Must not import any
framework, database driver, or HTTP client.

**Known pilot deviations** (tracked separately, to be cleaned up before #154
closes):
- `ServerType` is imported from `app.servers.models`, which transitively
  loads SQLAlchemy. `ServerType` itself is a standard-library `enum.Enum`
  so the surface API stays framework-free, but the import side-effect
  pulls SQLAlchemy onto the load path. This will be resolved by relocating
  `ServerType` to a domain-pure module as part of sub-issue #154-8
  (`servers/` domain refactor; see Issue #235 / #228 Option B).
  See `docs/ARCHITECTURE.md` §4.1.
"""

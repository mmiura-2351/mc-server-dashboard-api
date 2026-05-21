"""Domain layer for the groups module.

Contains pure domain entities (`entities.py`), Port (Protocol) definitions
(`ports.py`), and domain exceptions (`exceptions.py`). Must not import any
framework, database driver, or HTTP client.

**Known pilot deviations** (tracked separately, to be cleaned up before #154
closes):
- `GroupType` is imported from `app.groups.models`, which transitively
  loads SQLAlchemy. `GroupType` itself is a standard-library `enum.Enum`
  so the surface API stays framework-free, but the import side-effect
  pulls SQLAlchemy onto the load path. Follow-up issue is filed to
  relocate it to `app/groups/domain/value_objects.py` alongside
  `Role` (#253) and the upcoming `ServerType` move (#235).
- `AttachedServerView.status` carries a `ServerStatus` value imported
  from `app.servers.models`. Same shape of deviation; will be resolved
  alongside #235 when `ServerStatus` moves to a domain-pure module.

See `docs/ARCHITECTURE.md` §4.1.
"""

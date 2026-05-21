"""Domain layer for the servers module.

Contains pure domain entities (`entities.py`), Port (Protocol)
definitions (`ports.py`), and domain exceptions (`exceptions.py`). Must
not import any framework, database driver, or HTTP client.

**Known pilot deviations** (tracked under #235, cleaned up before #154
closes):

- `ServerType` and `ServerStatus` are imported from
  `app.servers.models`, which transitively loads SQLAlchemy. Both are
  plain `enum.Enum` classes so the surface API stays framework-free,
  but the import side effect pulls SQLAlchemy onto the load path.
  PR #3 of #228 folds in #235 to relocate them to a
  `app.servers.domain.value_objects` module that does not transitively
  load the ORM.

See `docs/ARCHITECTURE.md` §4.1.
"""

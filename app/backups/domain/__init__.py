"""Domain layer for the backups module.

Contains pure domain entities (`entities.py`), Port (Protocol) definitions
(`ports.py`), and domain exceptions (`exceptions.py`). Must not import any
framework, database driver, or HTTP client.

`BackupType` / `BackupStatus` value objects live at
`app.servers.domain.value_objects` (re-exported from `app.servers.models`
for the SQLAlchemy column declaration). The `Backup` ORM class itself
still lives at `app.servers.models.Backup`; adapters import it from
that module.

See `docs/ARCHITECTURE.md` §4.1.
"""

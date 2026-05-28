"""Domain layer for the backups module.

Contains pure domain entities (`entities.py`), Port (Protocol) definitions
(`ports.py`), and domain exceptions (`exceptions.py`). Must not import any
framework, database driver, or HTTP client.

`BackupType` / `BackupStatus` value objects live at
`app.servers.domain.value_objects` so that adjacent domain modules can
reference them without transitively loading SQLAlchemy. The `Backup`
ORM class lives at `app.backups.models.Backup` (relocated from
`app.servers.models` in Issue #263); adapters import it from that
module.

See `docs/app/ARCHITECTURE.md` Section 4.1.
"""

"""Domain layer for the backups module.

Contains pure domain entities (`entities.py`), Port (Protocol) definitions
(`ports.py`), and domain exceptions (`exceptions.py`). Must not import any
framework, database driver, or HTTP client.

**Known pilot deviations** (tracked separately, to be cleaned up before #154
closes):
- `BackupType` and `BackupStatus` are imported from `app.servers.models`,
  which transitively loads SQLAlchemy. Both are plain `enum.Enum`
  classes so the surface API stays framework-free, but the import side
  effect pulls SQLAlchemy onto the load path. Follow-up issue is filed
  to relocate them alongside the `Backup` ORM into
  `app/backups/models.py` (mirrors the same situation as the
  `Template` ORM under #255).
- The `Backup` SQLAlchemy ORM class itself still lives at
  `app.servers.models.Backup`; the adapter imports it from that
  module. Once #228 finalises the servers domain we can move the
  table alongside `BackupSchedule` / `BackupScheduleLog` (the latter
  two already live in `app/backups/models.py`).

See `docs/ARCHITECTURE.md` §4.1.
"""

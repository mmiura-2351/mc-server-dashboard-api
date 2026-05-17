"""Domain layer for the users module.

Contains pure domain entities, value objects, and Port (Protocol) definitions.
Must not import any framework, database driver, or HTTP client.

**Known pilot deviation** (same as `app/versions/`): `Role` is imported
from `app.users.models`, which transitively loads SQLAlchemy. `Role` is
itself a stdlib `enum.Enum` so the surface stays framework-free; the
side-effect cleanup happens when the `users/` model file is split between
`domain/value_objects.py` and `adapters/models.py` (deferred to a
follow-up). See `docs/ARCHITECTURE.md` §4.1.
"""

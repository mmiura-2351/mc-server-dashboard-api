"""In-memory fakes for the templates domain Ports.

`FakeTemplateRepository` and `FakeTemplatesUnitOfWork` structurally
implement the Protocols in `app.templates.domain.ports`. They let unit
tests exercise the templates application service without a database.

`FakeServerReadPort` is reused from `tests.unit.files.fakes` — it
already implements both `get_directory_path` (for #224) and `get`
(extended in #225 for templates), so duplicating it here would only
risk drift.
"""

from collections import Counter
from dataclasses import replace
from types import TracebackType
from typing import Any, Dict, List, Optional

from app.core.datetime_utils import utcnow
from app.servers.models import ServerType
from app.templates.domain.entities import (
    CreateTemplateCommand,
    TemplateEntity,
    TemplateListPage,
    TemplateListSpec,
    UpdateTemplateCommand,
)


def _visibility(
    entity: TemplateEntity, viewer_id: int, viewer_is_admin: bool
) -> bool:
    """Mirror the SQL-level filter applied by the SQLAlchemy adapter."""
    if viewer_is_admin:
        return True
    return entity.is_public or entity.created_by == viewer_id


class FakeTemplateRepository:
    """Dict-backed `TemplateRepository` for unit tests."""

    def __init__(self) -> None:
        self._records: Dict[int, TemplateEntity] = {}
        self._next_id = 1
        # Tracks dependent-server counts keyed by template_id; tests
        # configure this via `set_dependent_count`.
        self._dependents: Dict[int, int] = {}

    # ----- Reads -----

    async def get(self, template_id: int) -> Optional[TemplateEntity]:
        return self._records.get(template_id)

    async def find_by_creator_and_name(
        self, creator_id: int, name: str
    ) -> Optional[TemplateEntity]:
        for entity in self._records.values():
            if entity.created_by == creator_id and entity.name == name:
                return entity
        return None

    async def list_paged(self, spec: TemplateListSpec) -> TemplateListPage:
        visible = [
            e
            for e in self._records.values()
            if _visibility(e, spec.viewer_id, spec.viewer_is_admin)
        ]
        if spec.minecraft_version is not None:
            visible = [e for e in visible if e.minecraft_version == spec.minecraft_version]
        if spec.server_type is not None:
            visible = [e for e in visible if e.server_type == spec.server_type]
        if spec.is_public is not None:
            visible = [e for e in visible if e.is_public == spec.is_public]

        # created_at may be None for hand-built fixtures; treat None as
        # epoch-zero for sorting purposes.
        visible.sort(
            key=lambda e: e.created_at if e.created_at is not None else utcnow(),
            reverse=True,
        )

        total = len(visible)
        start = (spec.page - 1) * spec.size
        end = start + spec.size
        return TemplateListPage(
            entities=visible[start:end],
            total=total,
            page=spec.page,
            size=spec.size,
        )

    async def count_visible(self, viewer_id: int, viewer_is_admin: bool) -> int:
        return sum(
            1
            for e in self._records.values()
            if _visibility(e, viewer_id, viewer_is_admin)
        )

    async def count_visible_public(
        self, viewer_id: int, viewer_is_admin: bool
    ) -> int:
        return sum(
            1
            for e in self._records.values()
            if _visibility(e, viewer_id, viewer_is_admin) and e.is_public
        )

    async def count_owned_by(self, creator_id: int) -> int:
        return sum(1 for e in self._records.values() if e.created_by == creator_id)

    async def count_visible_by_server_type(
        self, viewer_id: int, viewer_is_admin: bool
    ) -> Dict[ServerType, int]:
        visible = [
            e
            for e in self._records.values()
            if _visibility(e, viewer_id, viewer_is_admin)
        ]
        counter: Counter = Counter(e.server_type for e in visible)
        result: Dict[ServerType, int] = {st: 0 for st in ServerType}
        for server_type, count in counter.items():
            result[server_type] = count
        return result

    async def count_active_dependent_servers(self, template_id: int) -> int:
        return self._dependents.get(template_id, 0)

    # ----- Writes -----

    async def add(self, command: CreateTemplateCommand) -> TemplateEntity:
        now = utcnow()
        entity = TemplateEntity(
            id=self._next_id,
            name=command.name,
            description=command.description,
            minecraft_version=command.minecraft_version,
            server_type=command.server_type,
            configuration=command.configuration,
            default_groups=command.default_groups,
            is_public=command.is_public,
            created_by=command.created_by,
            creator_name=None,
            created_at=now,
            updated_at=now,
        )
        self._records[self._next_id] = entity
        self._next_id += 1
        return entity

    async def update(
        self, template_id: int, command: UpdateTemplateCommand
    ) -> Optional[TemplateEntity]:
        existing = self._records.get(template_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            **command.applied_fields(),
            updated_at=utcnow(),
        )
        self._records[template_id] = updated
        return updated

    async def delete(self, template_id: int) -> bool:
        if template_id not in self._records:
            return False
        del self._records[template_id]
        return True

    # ----- Test helpers -----

    def seed(self, entity: TemplateEntity) -> TemplateEntity:
        """Insert a fully-formed entity (with id) for test fixtures."""
        assert entity.id is not None
        self._records[entity.id] = entity
        self._next_id = max(self._next_id, entity.id + 1)
        return entity

    def replace_record(self, record_id: int, **changes: Any) -> TemplateEntity:
        """Mutate a seeded entity (frozen dataclass)."""
        existing = self._records[record_id]
        updated = replace(existing, **changes)
        self._records[record_id] = updated
        return updated

    def set_dependent_count(self, template_id: int, count: int) -> None:
        """Configure the `count_active_dependent_servers` return value."""
        self._dependents[template_id] = count


class FakeTemplatesUnitOfWork:
    """In-memory `TemplatesUnitOfWork` for unit tests.

    Re-uses a single `FakeTemplateRepository` instance across enters
    so test setup carries through into the code under test.

    **Caveat**: `rollback()` does NOT actually undo changes made to the
    in-memory store — assert on the `rolled_back` counter or use
    hand-snapshotted state for before/after comparisons.
    """

    def __init__(
        self, templates: Optional[FakeTemplateRepository] = None
    ) -> None:
        self.templates: FakeTemplateRepository = templates or FakeTemplateRepository()
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> "FakeTemplatesUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


# Convenience: tests can build a TemplateEntity quickly via this helper
# without repeating every field.
def make_template_entity(
    *,
    id: int,
    created_by: int,
    name: str = "tpl",
    is_public: bool = False,
    server_type: ServerType = ServerType.vanilla,
    minecraft_version: str = "1.20.1",
    configuration: Optional[Dict[str, Any]] = None,
    default_groups: Optional[Dict[str, List[int]]] = None,
    description: Optional[str] = None,
    creator_name: Optional[str] = None,
) -> TemplateEntity:
    now = utcnow()
    return TemplateEntity(
        id=id,
        name=name,
        description=description,
        minecraft_version=minecraft_version,
        server_type=server_type,
        configuration=configuration if configuration is not None else {},
        default_groups=default_groups
        if default_groups is not None
        else {"op_groups": [], "whitelist_groups": []},
        is_public=is_public,
        created_by=created_by,
        creator_name=creator_name,
        created_at=now,
        updated_at=now,
    )

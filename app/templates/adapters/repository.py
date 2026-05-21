"""SQLAlchemy implementation of `TemplateRepository`.

Implements `app.templates.domain.ports.TemplateRepository`. The adapter
is the only layer that knows about the SQLAlchemy ORM and the
`Template` columns; it converts ORM rows to/from `TemplateEntity` so
the application layer never sees ORM types.

The `Template` ORM class currently lives at
`app.servers.models.Template` for historical reasons (no Alembic;
relocating the owning module needs careful import-ordering with the
`Server.template` back-population). The model is functionally a
templates-domain table; the import direction here
(`templates.adapters` → `servers.models`) is an artefact of file
placement, not a cross-domain Port bypass per `docs/ARCHITECTURE.md`
§4.3. Follow-up: see the issue linked from the #225 PR description for
the planned `app/templates/models.py` relocation.

Per the UnitOfWork pattern, repository methods **do not commit**. They
stage changes on the session and rely on the surrounding
`SqlAlchemyTemplatesUnitOfWork` (or the caller) to commit.
"""

from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.servers.models import Server, ServerType, Template
from app.templates.domain.entities import (
    CreateTemplateCommand,
    TemplateEntity,
    TemplateListPage,
    TemplateListSpec,
    UpdateTemplateCommand,
)


def _template_to_entity(row: Template) -> TemplateEntity:
    """Convert an ORM row into a domain entity.

    Reads `row.creator.username` eagerly. Callers that need this field
    must load the row with `joinedload(Template.creator)` so the access
    does not trigger a separate SELECT.
    """
    creator_name = row.creator.username if row.creator is not None else None
    # `get_configuration` / `get_default_groups` materialise the JSON
    # columns into plain dicts, regardless of how SQLAlchemy stored them.
    return TemplateEntity(
        id=row.id,
        name=row.name,
        description=row.description,
        minecraft_version=row.minecraft_version,
        server_type=row.server_type,
        configuration=row.get_configuration(),
        default_groups=row.get_default_groups(),
        is_public=row.is_public,
        created_by=row.created_by,
        creator_name=creator_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_visibility(query, viewer_id: int, viewer_is_admin: bool):
    """Restrict a Template query to rows the viewer is allowed to see."""
    if viewer_is_admin:
        return query
    return query.filter((Template.is_public) | (Template.created_by == viewer_id))


class SqlAlchemyTemplateRepository:
    """SQLAlchemy-backed implementation of the templates persistence Port.

    Does not commit. Callers must drive transactions via
    `TemplatesUnitOfWork` (production) or by explicitly committing the
    session (legacy paths, while shims still exist).
    """

    def __init__(self, db: Session):
        self.db = db

    # ===================
    # Reads
    # ===================

    async def get(self, template_id: int) -> Optional[TemplateEntity]:
        row = (
            self.db.query(Template)
            .options(joinedload(Template.creator))
            .filter(Template.id == template_id)
            .first()
        )
        return _template_to_entity(row) if row else None

    async def find_by_creator_and_name(
        self, creator_id: int, name: str
    ) -> Optional[TemplateEntity]:
        row = (
            self.db.query(Template)
            .options(joinedload(Template.creator))
            .filter(Template.created_by == creator_id, Template.name == name)
            .first()
        )
        return _template_to_entity(row) if row else None

    async def list_paged(self, spec: TemplateListSpec) -> TemplateListPage:
        query = self.db.query(Template).options(joinedload(Template.creator))
        query = _apply_visibility(query, spec.viewer_id, spec.viewer_is_admin)

        if spec.minecraft_version:
            query = query.filter(Template.minecraft_version == spec.minecraft_version)
        if spec.server_type is not None:
            query = query.filter(Template.server_type == spec.server_type)
        if spec.is_public is not None:
            query = query.filter(Template.is_public == spec.is_public)

        query = query.order_by(Template.created_at.desc())

        total = query.count()
        rows = query.offset((spec.page - 1) * spec.size).limit(spec.size).all()

        return TemplateListPage(
            entities=[_template_to_entity(r) for r in rows],
            total=total,
            page=spec.page,
            size=spec.size,
        )

    async def count_visible(self, viewer_id: int, viewer_is_admin: bool) -> int:
        query = self.db.query(Template)
        query = _apply_visibility(query, viewer_id, viewer_is_admin)
        return query.count()

    async def count_visible_public(self, viewer_id: int, viewer_is_admin: bool) -> int:
        query = self.db.query(Template)
        query = _apply_visibility(query, viewer_id, viewer_is_admin)
        return query.filter(Template.is_public).count()

    async def count_owned_by(self, creator_id: int) -> int:
        return self.db.query(Template).filter(Template.created_by == creator_id).count()

    async def count_visible_by_server_type(
        self, viewer_id: int, viewer_is_admin: bool
    ) -> Dict[ServerType, int]:
        query = self.db.query(Template)
        query = _apply_visibility(query, viewer_id, viewer_is_admin)
        rows = (
            query.with_entities(Template.server_type, func.count(Template.id))
            .group_by(Template.server_type)
            .all()
        )
        result: Dict[ServerType, int] = {st: 0 for st in ServerType}
        for server_type, count in rows:
            result[server_type] = count
        return result

    async def count_active_dependent_servers(self, template_id: int) -> int:
        """Count non-deleted servers referencing this template.

        Cross-domain query (touches `Server`). Lives on the templates
        repository because the `delete_template` use case needs it to
        enforce the "cannot delete in-use template" rule. The
        templates adapter is the natural owner: the query is keyed by
        `template_id` and there is no equivalent surface on the minimal
        `ServerReadPort`.
        """
        return (
            self.db.query(Server)
            .filter(
                Server.template_id == template_id,
                Server.is_deleted.is_(False),
            )
            .count()
        )

    # ===================
    # Writes
    # ===================

    async def add(self, command: CreateTemplateCommand) -> TemplateEntity:
        row = Template(
            name=command.name,
            description=command.description,
            minecraft_version=command.minecraft_version,
            server_type=command.server_type,
            configuration=command.configuration,
            default_groups=command.default_groups,
            created_by=command.created_by,
            is_public=command.is_public,
        )
        self.db.add(row)
        self.db.flush()
        # Populate the `creator` relation so `_template_to_entity` resolves
        # `creator_name` without a stray lazy SELECT. `refresh` issues one
        # targeted load instead of re-SELECTing the whole row.
        self.db.refresh(row, attribute_names=["creator", "created_at", "updated_at"])
        return _template_to_entity(row)

    async def update(
        self, template_id: int, command: UpdateTemplateCommand
    ) -> Optional[TemplateEntity]:
        row = (
            self.db.query(Template)
            .options(joinedload(Template.creator))
            .filter(Template.id == template_id)
            .first()
        )
        if row is None:
            return None

        # Sparse update: only the fields the caller actually set
        for field, value in command.applied_fields().items():
            setattr(row, field, value)

        self.db.flush()
        return _template_to_entity(row)

    async def delete(self, template_id: int) -> bool:
        row = self.db.query(Template).filter(Template.id == template_id).first()
        if row is None:
            return False
        self.db.delete(row)
        return True

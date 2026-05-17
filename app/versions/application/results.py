"""Application-layer result DTOs.

These types describe the *responses* of high-level use cases (as opposed
to the persistence entities in `domain/entities.py`, which model the
data the repository stores). Living in the application layer is correct:
they are part of the contract between the service and its callers
(routers / schedulers / management CLI), not part of the domain model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from app.versions.domain.entities import VersionUpdateLogEntity


@dataclass(frozen=True)
class VersionUpdateResult:
    """Outcome of one `update_versions` invocation."""

    success: bool
    message: str
    log_id: Optional[int] = None
    versions_added: int = 0
    versions_updated: int = 0
    versions_removed: int = 0
    execution_time_ms: Optional[int] = None
    errors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class UpdateStatus:
    """Current state of the version-update subsystem."""

    last_update: Optional[VersionUpdateLogEntity]
    total_versions: int
    versions_by_type: Dict[str, int]
    next_scheduled_update: Optional[datetime]
    is_update_running: bool

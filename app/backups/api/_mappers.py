"""Mapper helpers that convert domain entities to Pydantic wire schemas.

Kept in `api/` (not `domain/`) so the persistence boundary stays free
of Pydantic — and so the MB-conversion (`file_size_mb`) and other
wire-only computations live next to the response models that consume
them.
"""

from typing import List

from app.backups.application.scheduler import BackupSchedulerService
from app.backups.domain.entities import (
    BackupEntity,
    BackupScheduleEntity,
    BackupScheduleLogEntity,
    BackupStatistics,
)
from app.backups.schemas import (
    BackupResponse,
    BackupScheduleLogResponse,
    BackupScheduleResponse,
    BackupStatisticsResponse,
    SchedulerStatusResponse,
)


def backup_entity_to_response(entity: BackupEntity) -> BackupResponse:
    file_size_mb = round(entity.file_size / (1024 * 1024), 2) if entity.file_size else 0
    return BackupResponse(
        id=entity.id,
        server_id=entity.server_id,
        name=entity.name,
        description=entity.description,
        file_path=entity.file_path,
        file_size=entity.file_size,
        file_size_mb=file_size_mb,
        backup_type=entity.backup_type,
        status=entity.status,
        created_at=entity.created_at,
        server_name=entity.server_name,
        minecraft_version=entity.minecraft_version,
    )


def backup_statistics_to_response(
    stats: BackupStatistics,
) -> BackupStatisticsResponse:
    return BackupStatisticsResponse(
        total_backups=stats.total_backups,
        completed_backups=stats.completed_backups,
        failed_backups=stats.failed_backups,
        total_size_bytes=stats.total_size_bytes,
        total_size_mb=round(stats.total_size_bytes / (1024 * 1024), 2),
    )


def backup_schedule_entity_to_response(
    entity: BackupScheduleEntity,
) -> BackupScheduleResponse:
    return BackupScheduleResponse(
        id=entity.id,
        server_id=entity.server_id,
        interval_hours=entity.interval_hours,
        max_backups=entity.max_backups,
        enabled=entity.enabled,
        only_when_running=entity.only_when_running,
        last_backup_at=entity.last_backup_at,
        next_backup_at=entity.next_backup_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def backup_schedule_log_entity_to_response(
    entity: BackupScheduleLogEntity,
) -> BackupScheduleLogResponse:
    return BackupScheduleLogResponse(
        id=entity.id,
        server_id=entity.server_id,
        action=entity.action.value,
        reason=entity.reason,
        old_config=entity.old_config,
        new_config=entity.new_config,
        executed_by_user_id=entity.executed_by_user_id,
        executed_by_username=entity.executed_by_username,
        created_at=entity.created_at,
    )


def scheduler_status_to_response(
    scheduler: BackupSchedulerService,
    all_schedules: List[BackupScheduleEntity],
    enabled_schedules: List[BackupScheduleEntity],
) -> SchedulerStatusResponse:
    next_execution = None
    if enabled_schedules:
        next_times = [s.next_backup_at for s in enabled_schedules if s.next_backup_at]
        if next_times:
            next_execution = min(next_times)

    return SchedulerStatusResponse(
        is_running=scheduler.is_running,
        total_schedules=len(all_schedules),
        enabled_schedules=len(enabled_schedules),
        cache_size=scheduler.cache_size,
        next_execution=next_execution,
    )

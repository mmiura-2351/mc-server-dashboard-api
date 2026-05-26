"""Groups HTTP router.

Each endpoint depends on `get_group_service` and dispatches to the
hexagonal `GroupService` (`app.groups.application.service`). Domain
exceptions are mapped to HTTPException at the boundary so the
application layer never imports FastAPI.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.groups.api.dependencies import get_group_service
from app.groups.application.service import GroupService as _ApplicationGroupService
from app.groups.domain.exceptions import (
    GroupAccessError,
    GroupAlreadyExistsError,
    GroupHasAttachmentsError,
    GroupNotFoundError,
    PlayerNotFoundInGroup,
    ServerGroupAttachmentExistsError,
    ServerGroupAttachmentNotFoundError,
    ServerNotFoundForAttachment,
)
from app.groups.models import GroupType
from app.groups.schemas import (
    AttachedGroupResponse,
    AttachedServerResponse,
    GroupCreateRequest,
    GroupListResponse,
    GroupResponse,
    GroupServersResponse,
    GroupUpdateRequest,
    PlayerAddRequest,
    ServerAttachRequest,
    ServerGroupsResponse,
)
from app.users.domain.value_objects import Role
from app.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["groups"])


def _is_admin(user: User) -> bool:
    return user.role == Role.admin


def _entity_to_response(entity) -> GroupResponse:
    """Build a `GroupResponse` from a `GroupEntity` (domain) row."""
    from app.groups.schemas import PlayerSchema

    players = [
        PlayerSchema(
            uuid=player.get("uuid", ""),
            username=player.get("username", ""),
            added_at=player.get("added_at"),
        )
        for player in entity.players
    ]
    return GroupResponse(
        id=entity.id,
        name=entity.name,
        description=entity.description,
        type=entity.type,
        players=players,
        owner_id=entity.owner_id,
        is_template=entity.is_template,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    request: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Create a new group for managing OP or whitelist players."""
    try:
        entity = await group_service.create_group(
            actor_id=current_user.id,
            name=request.name,
            group_type=request.group_type,
            description=request.description,
        )
        return _entity_to_response(entity)
    except GroupAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create group: {str(e)}",
        )


@router.get("", response_model=GroupListResponse)
async def list_groups(
    group_type: Optional[GroupType] = Query(None, description="Filter by group type"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """List groups visible to the current user (Phase 1 = all groups).

    Pagination is handled SQL-side via LIMIT/OFFSET (Issue #365).
    ``total`` reflects the full filtered count so legacy clients keep
    working.
    """
    try:
        from app.core.pagination import build_pagination_meta

        result = await group_service.list_groups(
            actor_id=current_user.id,
            group_type=group_type,
            page=page,
            size=size,
        )
        responses = [_entity_to_response(e) for e in result.entities]
        pagination = build_pagination_meta(
            total=result.total, page=result.page, size=result.size
        )
        return GroupListResponse(
            groups=responses, total=result.total, pagination=pagination
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list groups: {str(e)}",
        )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Get group details by id."""
    try:
        entity = await group_service.get_group(
            actor_id=current_user.id, group_id=group_id
        )
        return _entity_to_response(entity)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get group: {str(e)}",
        )


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    request: GroupUpdateRequest,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Update group name / description."""
    try:
        entity = await group_service.update_group(
            actor_id=current_user.id,
            group_id=group_id,
            name=request.name,
            description=request.description,
        )
        return _entity_to_response(entity)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update group: {str(e)}",
        )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Delete a group (refuses if still attached to any server)."""
    try:
        await group_service.delete_group(actor_id=current_user.id, group_id=group_id)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupHasAttachmentsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete group: {str(e)}",
        )


# Player Management Endpoints


@router.post("/{group_id}/players", response_model=GroupResponse)
async def add_player_to_group(
    group_id: int,
    request: PlayerAddRequest,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Add (or upsert) a player into a group."""
    try:
        entity = await group_service.add_player(
            actor_id=current_user.id,
            group_id=group_id,
            uuid=request.uuid,
            username=request.username,
        )
        return _entity_to_response(entity)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add player to group: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add player to group: {str(e)}",
        )


@router.delete("/{group_id}/players/{player_uuid}", response_model=GroupResponse)
async def remove_player_from_group(
    group_id: int,
    player_uuid: str,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Remove a player from a group."""
    try:
        entity = await group_service.remove_player(
            actor_id=current_user.id, group_id=group_id, uuid=player_uuid
        )
        return _entity_to_response(entity)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PlayerNotFoundInGroup as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove player from group: {str(e)}",
        )


# Server Attachment Endpoints


@router.post("/{group_id}/servers")
async def attach_group_to_server(
    group_id: int,
    request: ServerAttachRequest,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Attach a group to a server (admin or server-owner only)."""
    try:
        await group_service.attach_group_to_server(
            actor_id=current_user.id,
            actor_is_admin=_is_admin(current_user),
            server_id=request.server_id,
            group_id=group_id,
            priority=request.priority,
        )
        return {"message": f"Group {group_id} attached to server {request.server_id}"}
    except ServerNotFoundForAttachment as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ServerGroupAttachmentExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to attach group to server: {str(e)}",
        )


@router.delete("/{group_id}/servers/{server_id}")
async def detach_group_from_server(
    group_id: int,
    server_id: int,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Detach a group from a server (admin or server-owner only)."""
    try:
        await group_service.detach_group_from_server(
            actor_id=current_user.id,
            actor_is_admin=_is_admin(current_user),
            server_id=server_id,
            group_id=group_id,
        )
        return {"message": f"Group {group_id} detached from server {server_id}"}
    except ServerNotFoundForAttachment as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ServerGroupAttachmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detach group from server: {str(e)}",
        )


@router.get("/{group_id}/servers", response_model=GroupServersResponse)
async def get_group_servers(
    group_id: int,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Return servers this group is attached to."""
    try:
        views = await group_service.get_group_servers(
            actor_id=current_user.id, group_id=group_id
        )
        responses = [
            AttachedServerResponse(
                id=v.id,
                name=v.name,
                status=v.status.value,
                priority=v.priority,
                attached_at=v.attached_at.isoformat(),
            )
            for v in views
        ]
        return GroupServersResponse(group_id=group_id, servers=responses)
    except GroupNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except GroupAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get group servers: {str(e)}",
        )


# Server Groups Endpoint


@router.get("/servers/{server_id}", response_model=ServerGroupsResponse)
async def get_server_groups(
    server_id: int,
    current_user: User = Depends(get_current_user),
    group_service: _ApplicationGroupService = Depends(get_group_service),
):
    """Return groups attached to the specified server."""
    try:
        views = await group_service.get_server_groups(
            actor_id=current_user.id, server_id=server_id
        )
        responses = [
            AttachedGroupResponse(
                id=v.id,
                name=v.name,
                description=v.description,
                type=v.type.value,
                priority=v.priority,
                attached_at=v.attached_at.isoformat(),
                player_count=v.player_count,
            )
            for v in views
        ]
        return ServerGroupsResponse(server_id=server_id, groups=responses)
    except ServerNotFoundForAttachment as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server groups: {str(e)}",
        )

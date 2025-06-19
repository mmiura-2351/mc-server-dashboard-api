import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.groups.models import GroupType
from app.groups.schemas import (
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
from app.services.authorization_service import authorization_service
from app.services.group_service import GroupService
from app.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["groups"])


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    request: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new group

    Creates a group for managing OP or whitelist players that can be
    attached to multiple servers.

    - **name**: Unique group name for the user
    - **group_type**: Either 'op' or 'whitelist'
    - **description**: Optional group description
    """
    try:
        # Phase 1: All users can create groups
        if not authorization_service.can_create_group(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to create groups",
            )

        group_service = GroupService(db)
        group = group_service.create_group(
            user=current_user,
            name=request.name,
            group_type=request.group_type,
            description=request.description,
        )

        return GroupResponse.from_orm(group)

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List user's groups

    Returns all groups owned by the current user, optionally filtered by type.
    """
    try:
        group_service = GroupService(db)
        groups = group_service.get_user_groups(current_user, group_type)

        group_responses = [GroupResponse.from_orm(group) for group in groups]

        return GroupListResponse(groups=group_responses, total=len(group_responses))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list groups: {str(e)}",
        )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get group details

    Returns detailed information about a specific group including all players.
    """
    try:
        group_service = GroupService(db)
        group = group_service.get_group_by_id(current_user, group_id)

        return GroupResponse.from_orm(group)

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
    db: Session = Depends(get_db),
):
    """
    Update group information

    Updates group name and description. Group type cannot be changed.
    """
    try:
        group_service = GroupService(db)
        group = group_service.update_group(
            user=current_user,
            group_id=group_id,
            name=request.name,
            description=request.description,
        )

        return GroupResponse.from_orm(group)

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
    db: Session = Depends(get_db),
):
    """
    Delete a group

    Deletes a group if it's not attached to any servers.
    """
    try:
        group_service = GroupService(db)
        group_service.delete_group(current_user, group_id)

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
    db: Session = Depends(get_db),
):
    """
    Add a player to a group

    Adds a player by UUID and username to the group. If the player
    already exists, updates their username.
    """
    try:
        group_service = GroupService(db)
        group = await group_service.add_player_to_group(
            user=current_user,
            group_id=group_id,
            uuid=request.uuid,
            username=request.username,
        )

        return GroupResponse.from_orm(group)

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Failed to add player to group: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add player to group: {str(e)}",
        )


@router.delete("/{group_id}/players/{player_uuid}", response_model=GroupResponse)
async def remove_player_from_group(
    group_id: int,
    player_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Remove a player from a group

    Removes a player by UUID from the group.
    """
    try:
        group_service = GroupService(db)
        group = await group_service.remove_player_from_group(
            user=current_user, group_id=group_id, uuid=player_uuid
        )

        return GroupResponse.from_orm(group)

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
    db: Session = Depends(get_db),
):
    """
    Attach a group to a server

    Attaches this group to a server with optional priority.
    Higher priority groups are processed first.
    """
    try:
        group_service = GroupService(db)
        await group_service.attach_group_to_server(
            user=current_user,
            server_id=request.server_id,
            group_id=group_id,
            priority=request.priority,
        )

        return {"message": f"Group {group_id} attached to server {request.server_id}"}

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
    db: Session = Depends(get_db),
):
    """
    Detach a group from a server

    Removes the attachment between this group and the specified server.
    """
    try:
        group_service = GroupService(db)
        await group_service.detach_group_from_server(
            user=current_user, server_id=server_id, group_id=group_id
        )

        return {"message": f"Group {group_id} detached from server {server_id}"}

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
    db: Session = Depends(get_db),
):
    """
    Get servers attached to a group

    Returns all servers that have this group attached.
    """
    try:
        group_service = GroupService(db)
        servers = group_service.get_group_servers(current_user, group_id)

        server_responses = [AttachedServerResponse(**server) for server in servers]

        return GroupServersResponse(group_id=group_id, servers=server_responses)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get group servers: {str(e)}",
        )


# Server Groups Endpoint (for getting groups attached to a server)


@router.get("/servers/{server_id}", response_model=ServerGroupsResponse)
async def get_server_groups(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get groups attached to a server

    Returns all groups attached to the specified server.
    """
    try:
        group_service = GroupService(db)
        groups = group_service.get_server_groups(current_user, server_id)

        from app.groups.schemas import AttachedGroupResponse

        group_responses = [AttachedGroupResponse(**group) for group in groups]

        return ServerGroupsResponse(server_id=server_id, groups=group_responses)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get server groups: {str(e)}",
        )

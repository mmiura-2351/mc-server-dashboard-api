from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.backups.domain.exceptions import (
    BackupNotFoundError,
    BackupParentServerMissingError,
)
from app.core.database import get_db
from app.servers.api.dependencies import get_authorization_service
from app.servers.application.authorization import AuthorizationService
from app.servers.domain.exceptions import ServerAccessError, ServerNotFoundError
from app.servers.models import ServerType
from app.templates.api.dependencies import get_template_service
from app.templates.application.service import (
    TemplateService as _ApplicationTemplateService,
)
from app.templates.domain.exceptions import (
    TemplateAccessError,
    TemplateError,
    TemplateNotFoundError,
)
from app.templates.schemas import (
    TemplateCloneRequest,
    TemplateCreateCustomRequest,
    TemplateCreateFromServerRequest,
    TemplateListResponse,
    TemplateResponse,
    TemplateStatisticsResponse,
    TemplateUpdateRequest,
)
from app.users.domain.value_objects import Role
from app.users.models import User

router = APIRouter(tags=["templates"])


def _is_admin(user: User) -> bool:
    return user.role == Role.admin


@router.post(
    "/from-server/{server_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template_from_server(
    server_id: int,
    request: TemplateCreateFromServerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
    auth: AuthorizationService = Depends(get_authorization_service),
):
    """
    Create a template from an existing server

    Creates a template by capturing the configuration and files from
    an existing server. This includes server.properties, plugin/mod
    configurations, and other important files.

    - **name**: Descriptive name for the template
    - **description**: Optional description
    - **is_public**: Whether other users can use this template
    """
    try:
        # Check server access
        await auth.check_server_access(server_id, current_user)

        # Only operators and admins can create templates
        if not AuthorizationService.can_create_template(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create templates",
            )

        entity = await template_service.create_template_from_server(
            server_id=server_id,
            name=request.name,
            creator_id=current_user.id,
            description=request.description,
            is_public=request.is_public,
        )

        return TemplateResponse.from_entity(entity)

    except TemplateNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except TemplateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create template: {str(e)}",
        )


@router.post("/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_template(
    request: TemplateCreateCustomRequest,
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    Create a custom template with specified configuration

    Creates a template from scratch with custom configuration.
    Useful for creating standardized server setups.

    - **name**: Template name
    - **minecraft_version**: Target Minecraft version
    - **server_type**: Server type (vanilla, forge, paper)
    - **configuration**: Custom server configuration
    - **default_groups**: Default OP/whitelist groups to attach
    - **is_public**: Whether template should be public
    """
    try:
        # Only operators and admins can create templates
        if not AuthorizationService.can_create_template(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create templates",
            )

        entity = await template_service.create_custom_template(
            name=request.name,
            minecraft_version=request.minecraft_version,
            server_type=request.server_type,
            configuration=request.configuration,
            creator_id=current_user.id,
            description=request.description,
            default_groups=request.default_groups,
            is_public=request.is_public,
        )

        return TemplateResponse.from_entity(entity)

    except TemplateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create template: {str(e)}",
        )


@router.get("/", response_model=TemplateListResponse)
async def list_templates(
    minecraft_version: Optional[str] = Query(
        None, description="Filter by Minecraft version"
    ),
    server_type: Optional[ServerType] = Query(None, description="Filter by server type"),
    is_public: Optional[bool] = Query(
        None, description="Filter by public/private status"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=100, description="Page size"),
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    List templates with filtering

    Returns a paginated list of templates. Users can see public templates
    and their own private templates. Admins can see all templates.
    """
    try:
        page_result = await template_service.list_templates(
            viewer_id=current_user.id,
            viewer_is_admin=_is_admin(current_user),
            minecraft_version=minecraft_version,
            server_type=server_type,
            is_public=is_public,
            page=page,
            size=size,
        )

        template_responses = [
            TemplateResponse.from_entity(entity) for entity in page_result.entities
        ]

        # Issue #76 (Phase 1): retain legacy ``page``/``size``/``total``
        # and additionally surface the canonical ``pagination`` block.
        from app.core.pagination import build_pagination_meta

        pagination = build_pagination_meta(
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
        )
        return TemplateListResponse(
            templates=template_responses,
            total=page_result.total,
            page=page_result.page,
            size=page_result.size,
            pagination=pagination,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list templates: {str(e)}",
        )


@router.get("/statistics", response_model=TemplateStatisticsResponse)
async def get_template_statistics(
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    Get template usage statistics

    Returns statistics about templates accessible to the current user.
    Includes total counts and distribution by server type.
    """
    try:
        stats = await template_service.get_template_statistics(
            viewer_id=current_user.id, viewer_is_admin=_is_admin(current_user)
        )
        return TemplateStatisticsResponse(**stats)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get template statistics: {str(e)}",
        )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    Get template details by ID

    Returns detailed information about a specific template.
    Users can only access public templates or their own templates.
    """
    try:
        entity = await template_service.get_template(
            template_id,
            viewer_id=current_user.id,
            viewer_is_admin=_is_admin(current_user),
        )
        if entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )

        return TemplateResponse.from_entity(entity)

    except TemplateAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get template: {str(e)}",
        )


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    request: TemplateUpdateRequest,
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    Update template

    Updates template information and configuration.
    Users can only update their own templates unless they are admin.
    """
    try:
        entity = await template_service.update_template(
            template_id=template_id,
            viewer_id=current_user.id,
            viewer_is_admin=_is_admin(current_user),
            name=request.name,
            description=request.description,
            configuration=request.configuration,
            default_groups=request.default_groups,
            is_public=request.is_public,
        )

        if entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )

        return TemplateResponse.from_entity(entity)

    except TemplateAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except TemplateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update template: {str(e)}",
        )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    Delete template

    Permanently deletes a template and its associated files.
    Users can only delete their own templates unless they are admin.
    Cannot delete templates that are currently in use by servers.
    """
    try:
        success = await template_service.delete_template(
            template_id,
            viewer_id=current_user.id,
            viewer_is_admin=_is_admin(current_user),
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )

    except TemplateAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except TemplateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete template: {str(e)}",
        )


@router.post(
    "/{template_id}/clone",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_template(
    template_id: int,
    request: TemplateCloneRequest,
    current_user: User = Depends(get_current_user),
    template_service: _ApplicationTemplateService = Depends(get_template_service),
):
    """
    Clone an existing template

    Creates a copy of an existing template with a new name.
    Users can clone any template they have access to.
    """
    try:
        # Only operators and admins can create templates
        if not AuthorizationService.can_create_template(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators and admins can create templates",
            )

        # NOTE: preserves the legacy router behaviour, which composes
        # `get_template` + `create_custom_template` rather than calling
        # `TemplateService.clone_template` (the latter is retained on the
        # service for shim parity but unused by this endpoint). See PR
        # description for the rationale.
        original_entity = await template_service.get_template(
            template_id,
            viewer_id=current_user.id,
            viewer_is_admin=_is_admin(current_user),
        )
        if original_entity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )

        cloned_entity = await template_service.create_custom_template(
            name=request.name,
            minecraft_version=original_entity.minecraft_version,
            server_type=original_entity.server_type,
            configuration=original_entity.configuration,
            creator_id=current_user.id,
            description=request.description or f"Cloned from {original_entity.name}",
            default_groups=original_entity.default_groups,
            is_public=request.is_public,
        )

        return TemplateResponse.from_entity(cloned_entity)

    except TemplateAccessError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except TemplateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (
        HTTPException,
        ServerNotFoundError,
        ServerAccessError,
        BackupNotFoundError,
        BackupParentServerMissingError,
    ):
        # Re-raise domain exceptions so the global handlers in
        # ``app.core.error_handlers`` can map them to HTTP responses
        # without being swallowed by the catch-all below (#273).
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clone template: {str(e)}",
        )

"""FastAPI router for the auth domain.

All endpoints depend on `AuthService` and `UserService` via DI — they
never see SQLAlchemy directly.
"""

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.audit.api.dependencies import get_audit_writer
from app.audit.application.legacy_facade import _extract_ip_address
from app.audit.domain.entities import AuditEventCommand
from app.audit.domain.ports import AuditWriter
from app.auth.api.dependencies import get_auth_service, get_brute_force_service
from app.auth.application.brute_force_service import BruteForceService, LockoutStatus
from app.auth.application.service import AuthService
from app.auth.auth import create_access_token
from app.core.config import settings
from app.types import DatabaseSession
from app.users.api.dependencies import get_user_service
from app.users.application.password_policy import get_password_policy
from app.users.application.service import UserService

router = APIRouter()


def _record_authentication_event(
    audit: AuditWriter,
    request: Request,
    *,
    action: str,
    user_id: Optional[int] = None,
    details: Optional[dict] = None,
    success: bool = True,
) -> None:
    """Mirror :class:`AuditService.log_authentication_event` byte-identically.

    Preserves the action-string format
    ``f"auth_{action}_{'success' if success else 'failure'}"``, the
    ``user_agent``/``success`` details prefix, ``resource_type``, and
    the IP-extraction helper used by the legacy facade.
    """
    audit_details = {
        "user_agent": request.headers.get("User-Agent", "Unknown"),
        "success": success,
        **(details or {}),
    }
    audit.record(
        AuditEventCommand(
            action=f"auth_{action}_{'success' if success else 'failure'}",
            resource_type="authentication",
            user_id=user_id,
            details=audit_details,
            ip_address=_extract_ip_address(request),
        )
    )


def _record_security_event(
    audit: AuditWriter,
    request: Request,
    *,
    event_type: str,
    severity: str,
    details: Optional[dict] = None,
    user_id: Optional[int] = None,
) -> None:
    """Mirror :class:`AuditService.log_security_event` byte-identically.

    Preserves the ``f"security_{event_type}"`` action, the
    ``resource_type="security"`` field, and the standard details
    payload (``event_type``, ``severity``, ``request_path``,
    ``user_agent``). Falls back to the request-scoped
    ``user_id_context`` (via ``get_current_user_id``) when ``user_id``
    is not supplied, matching the legacy facade.
    """
    from app.middleware.audit_middleware import get_current_user_id

    effective_user_id = user_id if user_id is not None else get_current_user_id()
    audit_details = {
        "event_type": event_type,
        "severity": severity,
        "request_path": str(request.url.path),
        "user_agent": request.headers.get("User-Agent", "Unknown"),
        **(details or {}),
    }
    audit.record(
        AuditEventCommand(
            action=f"security_{event_type}",
            resource_type="security",
            user_id=effective_user_id,
            details=audit_details,
            ip_address=_extract_ip_address(request),
        )
    )


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _extract_ip(request: Request) -> Optional[str]:
    """Extract the source IP used for brute-force tracking.

    Security note (Issue #73 review): trusting ``X-Forwarded-For`` /
    ``X-Real-IP`` unconditionally would let any attacker spoof an
    arbitrary source IP by setting the header, defeating per-IP
    lockout. We therefore honour the forwarded headers only when:

    1. ``TRUST_PROXY_HEADERS`` is explicitly enabled, AND
    2. the immediate peer (``request.client.host``) is listed in
       ``TRUSTED_PROXIES``.

    In all other cases the immediate peer address wins. Operators
    running behind a reverse proxy must opt in via the config knob;
    see ``docs/SECURITY.md``.
    """
    peer = request.client.host if request.client else None

    if settings.TRUST_PROXY_HEADERS:
        trusted = settings.trusted_proxies_list
        if peer is not None and peer in trusted:
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                # Use the left-most entry — the original client per
                # RFC 7239 §5.2 convention.
                first = forwarded_for.split(",")[0].strip()
                if first:
                    return first
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip.strip()
        # Peer is not a trusted proxy: fall through and use the peer
        # address itself (ignoring any spoofed headers).

    return peer


async def _artificial_delay() -> None:
    """Constant-time padding to deny timing-based username enumeration."""
    delay_ms = settings.BRUTE_FORCE_DELAY_MS
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)


def _parse_release_date() -> Optional[datetime]:
    raw = settings.PASSWORD_POLICY_RELEASE_DATE
    if not raw:
        return None
    try:
        # Accept either date or full ISO timestamp.
        if "T" in raw:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw + "T00:00:00+00:00")
    except ValueError:
        return None


def _password_warning_for(user_entity, password_attempt: str) -> Optional[str]:
    """Return a warning header value when *user_entity* is grandfathered.

    A user qualifies for the warning iff their stored password fails
    the *current* policy AND they have never rotated it since the
    release date (``password_set_at`` is NULL or older than the
    release). The plaintext-attempt is passed for policy evaluation —
    it must match the hashed password (already validated upstream).
    """
    policy = get_password_policy()
    if policy.is_valid(
        password_attempt,
        username=user_entity.username,
        email=user_entity.email,
    ):
        return None

    release = _parse_release_date()
    set_at = getattr(user_entity, "password_set_at", None)
    if set_at is None:
        return "weak-password"
    if release is not None:
        set_at_aware = set_at if set_at.tzinfo else set_at.replace(tzinfo=timezone.utc)
        if set_at_aware < release:
            return "weak-password"
    return None


@router.post("/token", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DatabaseSession,
    request: Request,
    response: Response,
    user_service: UserService = Depends(get_user_service),
    auth_service: AuthService = Depends(get_auth_service),
    brute_force: BruteForceService = Depends(get_brute_force_service),
    audit: AuditWriter = Depends(get_audit_writer),
):
    ip_address = _extract_ip(request)
    user_agent = request.headers.get("User-Agent")
    username = form_data.username or ""

    # ----- Pre-flight lockout check -----
    lockout = await brute_force.check_lockout(username, ip_address)
    if lockout.locked:
        await _artificial_delay()
        _record_authentication_event(
            audit,
            request,
            action="login",
            details={
                "username": username,
                "reason": lockout.reason or "locked",
                "retry_after": lockout.retry_after_seconds,
            },
            success=False,
        )
        # The error body intentionally mirrors the standard credential
        # failure so an attacker cannot infer lockout state from the
        # response body alone — only the `Retry-After` header reveals
        # it, which is necessary RFC 6585 metadata.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(lockout.retry_after_seconds)},
        )

    user_entity = None
    try:
        user_entity = await user_service.authenticate_user(
            form_data.username, form_data.password
        )
        if user_entity is None:
            triggered = await brute_force.record_attempt(
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                failure_reason="invalid_credentials",
            )
            db.commit()
            await _artificial_delay()
            _audit_lockout_trigger(audit, request, username, triggered)
            _record_authentication_event(
                audit,
                request,
                action="login",
                details={
                    "username": username,
                    "reason": "invalid_credentials",
                },
                success=False,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )

        access_token = create_access_token(
            data={"sub": user_entity.username, "tv": user_entity.token_version}
        )
        refresh_token = await auth_service.create_refresh_token(user_entity.id)

        await brute_force.record_attempt(
            username=user_entity.username,
            ip_address=ip_address,
            user_agent=user_agent,
            success=True,
        )
        db.commit()

        warning = _password_warning_for(user_entity, form_data.password)
        if warning:
            response.headers["X-Password-Policy-Warning"] = warning

        _record_authentication_event(
            audit,
            request,
            action="login",
            user_id=user_entity.id,
            details={
                "username": user_entity.username,
                "user_role": user_entity.role.value,
            },
            success=True,
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
    except HTTPException as e:
        if user_entity is None and e.status_code not in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_429_TOO_MANY_REQUESTS,
        ):
            # `authenticate_user` raised something other than the
            # canonical 401 (e.g. 403 for pending approval). Record
            # as a failed attempt without bumping toward lockout —
            # legitimate pending-approval accounts shouldn't be
            # punished — but still audit the event.
            triggered = await brute_force.record_attempt(
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                success=False,
                failure_reason="authentication_error",
            )
            db.commit()
            _audit_lockout_trigger(audit, request, username, triggered)
            _record_authentication_event(
                audit,
                request,
                action="login",
                details={
                    "username": username,
                    "reason": "authentication_error",
                    "error": str(e.detail),
                },
                success=False,
            )
        raise


def _audit_lockout_trigger(
    audit: AuditWriter,
    request: Request,
    username: str,
    triggered: Optional[LockoutStatus],
) -> None:
    if triggered is None:
        return
    if triggered.reason == "account_locked":
        _record_security_event(
            audit,
            request,
            event_type="account_locked",
            severity="warning",
            details={
                "username": username,
                "lockout_seconds": triggered.retry_after_seconds,
            },
        )
    elif triggered.reason == "ip_locked":
        _record_security_event(
            audit,
            request,
            event_type="brute_force_ip_blocked",
            severity="warning",
            details={
                "lockout_seconds": triggered.retry_after_seconds,
            },
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    token_request: RefreshTokenRequest,
    db: DatabaseSession,
    request: Request,
    user_service: UserService = Depends(get_user_service),
    auth_service: AuthService = Depends(get_auth_service),
    audit: AuditWriter = Depends(get_audit_writer),
):
    user_id = await auth_service.verify_refresh_token(token_request.refresh_token)
    if not user_id:
        _record_authentication_event(
            audit,
            request,
            action="token_refresh",
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await user_service.get_user_by_id(user_id)
    if user is None or not user.is_active:
        _record_authentication_event(
            audit,
            request,
            action="token_refresh",
            user_id=user_id,
            details={"reason": "user_inactive_or_not_found"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access_token = create_access_token(
        data={"sub": user.username, "tv": user.token_version}
    )
    new_refresh_token = await auth_service.create_refresh_token(user.id)

    _record_authentication_event(
        audit,
        request,
        action="token_refresh",
        user_id=user.id,
        details={"username": user.username},
        success=True,
    )

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
async def logout(
    token_request: RefreshTokenRequest,
    db: DatabaseSession,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    audit: AuditWriter = Depends(get_audit_writer),
):
    user_id = await auth_service.verify_refresh_token(token_request.refresh_token)
    success = await auth_service.revoke_refresh_token(token_request.refresh_token)
    if not success:
        _record_authentication_event(
            audit,
            request,
            action="logout",
            user_id=user_id,
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        )

    _record_authentication_event(
        audit,
        request,
        action="logout",
        user_id=user_id,
        details={"logout_method": "refresh_token_revocation"},
        success=True,
    )

    return {"message": "Successfully logged out"}

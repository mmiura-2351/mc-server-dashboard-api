"""FastAPI authentication dependencies.

Issue #237 reshapes this module so that *every* code path that resolves
a JWT to a `User` runs through the single ``_authenticate`` helper. That
gives us one place to enforce all three liveness invariants:

1. The signature/expiry of the JWT is intact.
2. The user still exists and is still active.
3. The JWT's ``tv`` (token-version) claim matches the user's current
   ``token_version`` column — i.e. the credential has not been revoked
   by a deactivation, password change, or admin-forced logout since the
   token was issued.

On a ``tv`` mismatch we additionally emit an audit security event so
operators can spot post-revocation token abuse attempts.
"""

import logging
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.auth import decode_token
from app.core.database import get_db
from app.users import models

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def _emit_token_revoked_audit(
    *,
    request: Optional[Request],
    user: models.User,
    presented_tv: int,
) -> None:
    """Best-effort audit log for a ``tv`` mismatch.

    The audit infrastructure is request-scoped, so WebSocket call sites
    (which do not have a ``Request``) silently skip the emit. We also
    swallow any unexpected exception — failing the request because the
    audit sink hiccupped would be worse than the missing log entry.
    """
    if request is None:
        return
    try:
        # Local import to avoid a circular dependency:
        # `app.audit.application.legacy_facade` imports from
        # `app.users.adapters` which transitively pulls auth helpers.
        from app.audit.service import AuditService

        AuditService.log_security_event(
            request=request,
            event_type="token_revoked_post_deactivation",
            severity="warning",
            user_id=user.id,
            details={
                "username": user.username,
                "presented_token_version": presented_tv,
                "current_token_version": user.token_version,
            },
        )
    except Exception:  # pragma: no cover - audit must never break auth
        logger.exception("Failed to emit token_revoked audit event")


def _authenticate(
    token: str,
    db: Session,
    *,
    request: Optional[Request] = None,
) -> models.User:
    """Resolve *token* to a live, non-revoked ``User`` row.

    Raises ``HTTPException(401)`` for any of:

    * Malformed / expired / forged JWT.
    * Unknown ``sub`` (user deleted).
    * ``is_active == False`` (account deactivated).
    * ``tv`` claim does not match ``user.token_version`` (token revoked
      by a deactivation / password change / forced logout *after* the
      token was issued).

    All four conditions deliberately surface the same 401 response to
    deny an attacker the ability to distinguish "user gone" from
    "token revoked" from "token expired".
    """
    payload = decode_token(token)
    if payload is None:
        raise _CREDENTIALS_EXCEPTION

    username = payload.get("sub")
    if not isinstance(username, str):
        raise _CREDENTIALS_EXCEPTION

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise _CREDENTIALS_EXCEPTION

    if not user.is_active:
        # Defense-in-depth: even if the caller still holds a token
        # whose `tv` happens to match (e.g. deactivation happened
        # without bumping `token_version`, or via a code path we've
        # missed), a deactivated user MUST NOT authenticate.
        raise _CREDENTIALS_EXCEPTION

    presented_tv = payload.get("tv", 0)
    # NOTE: ``bool`` is a subclass of ``int`` in Python, so ``isinstance(True, int)``
    # is ``True``. Reject bools explicitly to prevent a ``"tv": true`` claim from
    # being treated as ``1`` and bypassing the version check.
    if not isinstance(presented_tv, int) or isinstance(presented_tv, bool):
        raise _CREDENTIALS_EXCEPTION

    current_tv = user.token_version or 0
    if presented_tv != current_tv:
        _emit_token_revoked_audit(request=request, user=user, presented_tv=presented_tv)
        raise _CREDENTIALS_EXCEPTION

    return user


def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    """HTTP dependency: resolve the bearer token to a live ``User``."""
    return _authenticate(token, db, request=request)


async def get_current_user_ws(token: str, db: Session) -> models.User:
    """WebSocket authentication dependency.

    Does not have a ``Request`` (FastAPI WS handlers receive
    ``WebSocket`` instead), so audit emission for ``tv`` mismatch is
    skipped — matching the legacy behaviour of this code path which
    has never written to the audit log.
    """
    return _authenticate(token, db, request=None)

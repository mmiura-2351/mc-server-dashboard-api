"""Application-layer result DTOs for the users domain.

These describe responses of high-level use cases. Living in the
application layer is correct: they are part of the contract between the
service and its callers (routers / scripts), not part of the domain
model.
"""

from dataclasses import dataclass

from app.users.domain.entities import UserEntity


@dataclass(frozen=True)
class UserWithToken:
    """A user plus a freshly-issued access token.

    Returned by self-service flows where the access token may need to be
    refreshed because something in `sub` changed (e.g. username) or
    because the credential surface changed (password rotation).
    """

    user: UserEntity
    access_token: str

"""DEPRECATED: re-export shim for `app.servers.application.authorization`.

Relocated under #228 (PR 2b/?). The module-level
``authorization_service`` singleton has been removed because every
production router now obtains an instance through FastAPI DI
(``Depends(get_authorization_service)``). Tests that still need the
class can import ``AuthorizationService`` from either path.
"""

from app.servers.application.authorization import AuthorizationService

__all__ = ["AuthorizationService"]

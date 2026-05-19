"""Backwards-compatible re-export of the audit router.

The router definition lives in `app.audit.api.router`. `app.main` keeps
importing `from app.audit.router import router` unchanged.
"""

from app.audit.api.router import router

__all__ = ["router"]

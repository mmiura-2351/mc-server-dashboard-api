"""DEPRECATED: re-export shim. See #228 PR 2f.

The implementation now lives at
`app.core.visibility.application.migration`. This shim preserves the
legacy import path so external callers can migrate without touching the
import line at the same time. Will be deleted by PR #3 (sweep).
"""

from app.core.visibility.application.migration import VisibilityMigrationService

__all__ = ["VisibilityMigrationService"]

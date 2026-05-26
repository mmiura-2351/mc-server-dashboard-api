"""Internal compatibility helpers for the minecraft sub-package.

The original :mod:`app.servers.application.minecraft_server` module
exposed a handful of module-level names (``logger``,
``java_compatibility_service``) that the test suite patches via
``mock.patch("app.servers.application.minecraft_server.<name>", ...)``.
After the split (Issue #155) the implementation lives in sibling
modules, but the patch target is still the shim. To keep every existing
patch site authoritative without rewriting the ~170 call sites that
reference these symbols, each split module imports
``logger`` / ``java_compatibility_service`` proxy objects from here
that forward every attribute lookup back to the shim module at call
time.

This indirection is the *only* concession to test compatibility — the
underlying behavior, log messages, and call shapes are preserved
byte-for-byte.
"""

from __future__ import annotations

import sys
from typing import Any


class _ShimAttrProxy:
    """Proxy that lazily resolves an attribute on the shim module.

    Attribute access on this proxy (``proxy.info(...)``) looks up the
    underlying name on :mod:`app.servers.application.minecraft_server`
    every time, so :func:`unittest.mock.patch` calls that swap the
    shim's attribute are observed by callers that hold this proxy.
    """

    __slots__ = ("_attr_name",)

    def __init__(self, attr_name: str) -> None:
        object.__setattr__(self, "_attr_name", attr_name)

    def _resolve(self) -> Any:
        shim = sys.modules.get("app.servers.application.minecraft_server")
        if shim is None:
            # Import lazily; the shim re-exports the real objects.
            import app.servers.application.minecraft_server as shim  # noqa: F401
        return getattr(shim, self._attr_name)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._resolve(), item)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        try:
            return repr(self._resolve())
        except Exception:
            return f"<_ShimAttrProxy {self._attr_name!r} unresolved>"


# Proxies that test patches target through the shim. Importing one of
# these in a split module gives that module a stand-in for the real
# object; every attribute access on the proxy re-reads from the shim.
logger = _ShimAttrProxy("logger")
java_compatibility_service = _ShimAttrProxy("java_compatibility_service")

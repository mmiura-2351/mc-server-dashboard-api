"""Health check domain.

Provides liveness and readiness probes plus a detailed admin-only
component report. Layered after the hexagonal layout (ARCHITECTURE
Section 4.2): the ``application`` layer is framework-agnostic, ``adapters``
talk to the rest of the codebase via Ports, and the ``api`` layer is
the FastAPI surface.

Scope: Phase 1 of Issue #21 — endpoints + per-component checks. Phase 2
(Prometheus-style metrics export) is tracked separately.
"""

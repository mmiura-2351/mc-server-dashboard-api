# In-memory SQLite database for the test suite.
import os
import shutil
import sys
import tempfile

# Raise the recursion limit before any `app.*` import so the pydantic-settings
# construction path (which materialises many validators per Settings instance
# and is exercised once per xdist worker boot) has more headroom. Under CI
# (4 vCPU runners with xdist `loadscope`), a single worker has been observed
# to hit ``RecursionError: maximum recursion depth exceeded`` during settings
# construction; the failure is not reproducible locally because thread/heap
# layout differs. Bumping the limit from the default 1000 to 5000 is cheap
# and bounded by the call stack we actually generate (~200 frames typical).
# Tracking: PR #333 review follow-up.
sys.setrecursionlimit(5000)


# Use a worker-specific database file to isolate parallel execution.
def get_worker_db_path():
    """Get worker-specific database path for parallel execution isolation."""
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    return os.path.join(tempfile.gettempdir(), f"test_mc_server_{worker_id}.db")


# IMPORTANT: set DATABASE_URL BEFORE any `from app.*` import so that
# `app.core.database.engine` and `app.main` lifespan startup target the
# worker-specific SQLite file. Without this, every xdist worker hits the
# shared `./app.db` from `.env` and `Base.metadata.create_all` races into
# "database is locked" errors. See Issue #210.
test_db_path = get_worker_db_path()
os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"

# Issue #22 Phase 1: signal the test environment so the per-env defaults
# overlay applies (e.g. LOG_FORMAT, DATABASE_MAX_RETRIES fast-fail semantics).
# ``setdefault`` keeps any explicit caller override.
os.environ.setdefault("ENVIRONMENT", "testing")

# The testing overlay sets AUTO_SYNC_ON_STARTUP=False and
# KEEP_SERVERS_ON_SHUTDOWN=False to keep app startup quiet during unit tests.
# However, several infrastructure tests (e.g.
# ``tests/infrastructure/servers/test_process_persistence.py``) exercise the
# real discovery / persistence code paths and expect master-compatible
# behaviour. Reinstate the master defaults for the suite as a whole; individual
# tests that need the overlay values can still monkeypatch the settings.
os.environ.setdefault("AUTO_SYNC_ON_STARTUP", "true")
os.environ.setdefault("KEEP_SERVERS_ON_SHUTDOWN", "true")

# The testing overlay drops DATABASE_MAX_RETRIES to 1 (fast-fail semantics),
# but xdist driving the worker-local sqlite file at full parallelism makes a
# single retry surface transient "database is locked" errors during heavy
# parallel suite execution (see Issue #210). Pin retries to 3 for the suite
# here while keeping the overlay default in place for real app code paths.
os.environ.setdefault("DATABASE_MAX_RETRIES", "3")

# Drop any stale per-worker DB left behind by a previous session so
# schema changes (e.g. new columns from a freshly-checked-out branch)
# are picked up on the first `Base.metadata.create_all`. Without this
# a `users` table missing the new `password_set_at` column survives
# across runs and triggers "no such column" errors. See Issue #73.
for _suffix in ("", "-journal", "-shm", "-wal"):
    _stale = test_db_path + _suffix
    if os.path.exists(_stale):
        try:
            os.remove(_stale)
        except OSError:
            pass

# Issue #73: relax the password policy and disable brute-force lockout
# by default for the test suite. Individual tests that exercise these
# features should re-enable them explicitly via `monkeypatch.setenv`
# or `BruteForceService` direct calls. These overlays must run before
# `app.core.config.settings` is imported.
os.environ.setdefault("PASSWORD_MIN_LENGTH", "8")
os.environ.setdefault("PASSWORD_REQUIRE_COMPLEXITY", "false")
os.environ.setdefault("PASSWORD_CHECK_COMMON_LIST", "false")
os.environ.setdefault("PASSWORD_FORBID_USER_INFO", "false")
os.environ.setdefault("PASSWORD_FORBID_SIMPLE_PATTERNS", "false")
os.environ.setdefault("BRUTE_FORCE_ENABLED", "false")
os.environ.setdefault("BRUTE_FORCE_DELAY_MS", "0")

from unittest.mock import Mock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.users.adapters.uow import SqlAlchemyUsersUnitOfWork  # noqa: E402
from app.users.application.service import UserService  # noqa: E402
from app.users.domain.value_objects import Role  # noqa: E402

# Shared helpers; safe to import here because they themselves only import
# from `app.*` (which is now configured with the worker-local DATABASE_URL).
from tests.helpers.auth import auth_headers_for  # noqa: E402
from tests.helpers.security import pwd_context  # noqa: E402,F401  (re-exported)
from tests.helpers.servers import make_server  # noqa: E402
from tests.helpers.users import make_user  # noqa: E402

SQLALCHEMY_DATABASE_URL = f"sqlite:///{test_db_path}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False,
)


# Issue #79 Phase 1: relax SQLite durability settings for the test suite.
# These PRAGMAs are SAFE TO LOSE because the per-worker DB file is created
# fresh each session (`pytest_sessionfinish` deletes it) and never holds
# production data. Together they remove every fsync on COMMIT and keep the
# rollback journal + temp tables in RAM, which materially cuts wall-clock
# for write-heavy fixtures (user create, server insert, backup metadata).
#
# - journal_mode=MEMORY: rollback journal kept in process memory rather
#   than written to disk on every transaction. A crash mid-transaction
#   can corrupt the DB — acceptable for ephemeral test DBs.
# - synchronous=OFF: skip the fsync that SQLite normally issues after the
#   journal write. Equivalent risk profile to MEMORY journal.
# - temp_store=MEMORY: keep CREATE TEMP TABLE / sorter scratch in RAM
#   instead of `/tmp` — relevant for the few ORDER BY queries in tests.
@event.listens_for(engine, "connect")
def _set_sqlite_pragma_for_tests(dbapi_conn, _):  # pragma: no cover - infra
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=MEMORY")
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA temp_store=MEMORY")
    finally:
        cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def pytest_sessionfinish(session, exitstatus):
    """Remove the worker-specific test database file at session end.

    Each worker only deletes its own file to avoid race conditions.
    """
    # Dispose the shared SQLAlchemy engine so its pooled sqlite connections are
    # closed deterministically rather than reaped by GC (which emits
    # ResourceWarning under `-W error::ResourceWarning`).
    try:
        engine.dispose()
    except Exception as e:
        # Surface failures via the warning summary so a real dispose regression
        # is not silently swallowed during session teardown.
        import warnings

        warnings.warn(f"Failed to dispose testing engine: {e}")
    try:
        current_worker_db = get_worker_db_path()
        if os.path.exists(current_worker_db):
            os.remove(current_worker_db)
    except Exception as e:
        # Log the failure but do not fail the test session because of it.
        import warnings

        warnings.warn(f"Failed to cleanup test database {current_worker_db}: {e}")


def _java_available() -> bool:
    """Return True when a `java` executable is reachable on PATH."""
    return shutil.which("java") is not None


def pytest_collection_modifyitems(config, items):
    """Auto-skip `@pytest.mark.requires_java` tests when no JRE is on PATH."""
    if _java_available():
        return
    skip_marker = pytest.mark.skip(reason="requires_java: no JRE on PATH")
    for item in items:
        if "requires_java" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session", autouse=True)
def _create_schema_once():
    """Materialize the DB schema once per worker session.

    Previously `Base.metadata.create_all` ran inside the function-scoped
    `db` fixture, paying the metadata reflection + DDL cost on every
    test. The schema is identical for the whole session (no migrations
    run between tests), so once per worker is sufficient. Per-test
    isolation is still provided by the table-DELETE cleanup in the
    `db` fixture below. Issue #79 Phase 1 / P3.
    """
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(scope="function")
def db(_create_schema_once):
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        # Close the session.
        db.close()
        # Clear all tables (lighter than dropping and recreating).
        with engine.connect() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
            conn.commit()


@pytest.fixture(scope="function")
def client(db):
    """
    Function-scoped TestClient to ensure proper isolation between tests
    in parallel execution. Each test gets a fresh client instance.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user(db):
    """Create a test user."""
    return make_user(
        db,
        username="testuser",
        email="test@example.com",
        password="testpassword",
        role=Role.user,
        is_approved=True,
    )


@pytest.fixture
def admin_user(db):
    """Create a test admin user."""
    return make_user(
        db,
        username="admin",
        email="admin@example.com",
        password="adminpassword",
        role=Role.admin,
        is_approved=True,
    )


@pytest.fixture
def unapproved_user(db):
    """Create an unapproved test user."""
    return make_user(
        db,
        username="unapproved",
        email="unapproved@example.com",
        password="unapprovedpassword",
        role=Role.user,
        is_approved=False,
    )


@pytest.fixture
def operator_user(db):
    """Create a test operator user."""
    return make_user(
        db,
        username="operator",
        email="operator@example.com",
        password="operatorpassword",
        role=Role.operator,
        is_approved=True,
    )


@pytest.fixture
def user_service(db):
    """Provide a UserService instance."""
    return UserService(uow=SqlAlchemyUsersUnitOfWork(db=db))


@pytest.fixture
def admin_headers(admin_user):
    """Generate admin auth headers (JWT issued directly, not via login)."""
    return auth_headers_for(admin_user.username)


@pytest.fixture
def user_headers(test_user):
    """Generate regular-user auth headers (JWT issued directly, not via login)."""
    return auth_headers_for(test_user.username)


@pytest.fixture
def operator_headers(operator_user):
    """Generate operator auth headers (JWT issued directly, not via login)."""
    return auth_headers_for(operator_user.username)


@pytest.fixture
def unapproved_headers(unapproved_user):
    """Generate unapproved-user auth headers (JWT issued directly, not via login)."""
    return auth_headers_for(unapproved_user.username)


@pytest.fixture
def sample_server(db, admin_user):
    """Create a test server."""
    return make_server(db, admin_user)


@pytest.fixture
def mock_request():
    """Mock FastAPI Request object for testing audit functions"""
    mock_req = Mock()
    mock_req.url.path = "/test/endpoint"
    mock_req.method = "POST"
    mock_req.headers = {
        "User-Agent": "TestClient/1.0",
        "X-Forwarded-For": "192.168.1.100",
    }
    mock_req.query_params = {}
    mock_req.client.host = "192.168.1.100"
    mock_req.state = Mock()
    return mock_req

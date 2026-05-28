"""Tests that verify test isolation under parallel execution."""

import os
import tempfile

from tests.conftest import get_worker_db_path


def test_worker_db_isolation():
    """The worker-specific database path is properly isolated."""
    db_path = get_worker_db_path()

    # The path must be worker-specific.
    assert "test_mc_server_" in db_path
    assert db_path.endswith(".db")

    # The path must live under the system temporary directory.
    temp_dir = tempfile.gettempdir()
    assert db_path.startswith(temp_dir)


def test_database_file_creation(db):
    """The database file is created correctly."""
    db_path = get_worker_db_path()

    # The database file must exist.
    assert os.path.exists(db_path)

    # The database connection must be usable.
    assert db is not None
    assert hasattr(db, "execute")


def test_test_isolation_simple_data(db):
    """Data is isolated between tests (simple test 1)."""
    from app.users.domain.value_objects import Role
    from app.users.models import User
    from tests.helpers.users import make_user

    # Create a test user.
    make_user(
        db,
        username="isolation_test_1",
        email="test1@isolation.com",
        password="password",
        role=Role.user,
        is_approved=True,
    )

    # The user must exist.
    found_user = db.query(User).filter(User.username == "isolation_test_1").first()
    assert found_user is not None
    assert found_user.email == "test1@isolation.com"


def test_test_isolation_different_data(db):
    """Data is isolated between tests (simple test 2)."""
    from app.users.domain.value_objects import Role
    from app.users.models import User
    from tests.helpers.users import make_user

    # Create a different test user.
    make_user(
        db,
        username="isolation_test_2",
        email="test2@isolation.com",
        password="password",
        role=Role.admin,
        is_approved=True,
    )

    # The previous test's user must not exist (isolation in effect).
    previous_user = db.query(User).filter(User.username == "isolation_test_1").first()
    assert previous_user is None

    # The current user must exist.
    current_user = db.query(User).filter(User.username == "isolation_test_2").first()
    assert current_user is not None
    assert current_user.role == Role.admin

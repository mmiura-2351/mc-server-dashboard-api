"""Service-level unit tests for `AuthService` driven by Fake UoW."""

import pytest

from app.auth.application.service import AuthService
from tests.unit.auth.fakes import FakeAuthUnitOfWork


@pytest.fixture
def uow() -> FakeAuthUnitOfWork:
    return FakeAuthUnitOfWork()


@pytest.fixture
def service(uow: FakeAuthUnitOfWork) -> AuthService:
    return AuthService(uow=uow)


class TestRefreshTokenLifecycle:
    @pytest.mark.asyncio
    async def test_create_and_verify(
        self, service: AuthService, uow: FakeAuthUnitOfWork
    ) -> None:
        token = await service.create_refresh_token(user_id=42)
        assert isinstance(token, str)
        assert len(token) > 0
        user_id = await service.verify_refresh_token(token)
        assert user_id == 42

    @pytest.mark.asyncio
    async def test_create_revokes_previous_token(self, service: AuthService) -> None:
        first = await service.create_refresh_token(user_id=42)
        second = await service.create_refresh_token(user_id=42)
        assert first != second
        # First token should now be invalid (revoked)
        assert await service.verify_refresh_token(first) is None
        # Second one is valid
        assert await service.verify_refresh_token(second) == 42

    @pytest.mark.asyncio
    async def test_verify_unknown_token_returns_none(self, service: AuthService) -> None:
        assert await service.verify_refresh_token("no-such-token") is None

    @pytest.mark.asyncio
    async def test_revoke_round_trip(self, service: AuthService) -> None:
        token = await service.create_refresh_token(user_id=42)
        assert await service.revoke_refresh_token(token) is True
        assert await service.verify_refresh_token(token) is None

    @pytest.mark.asyncio
    async def test_revoke_missing_returns_false(self, service: AuthService) -> None:
        assert await service.revoke_refresh_token("ghost") is False


class TestCommitDiscipline:
    @pytest.mark.asyncio
    async def test_writes_commit(
        self, service: AuthService, uow: FakeAuthUnitOfWork
    ) -> None:
        await service.create_refresh_token(user_id=1)
        assert uow.committed >= 1

    @pytest.mark.asyncio
    async def test_pure_read_does_not_commit(
        self, service: AuthService, uow: FakeAuthUnitOfWork
    ) -> None:
        await service.verify_refresh_token("nope")
        assert uow.committed == 0

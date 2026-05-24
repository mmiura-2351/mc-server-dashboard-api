import pytest

from app.versions.domain.stability import is_stable_version


@pytest.mark.parametrize(
    "version_string",
    [
        "1.21",
        "1.21.6",
        "1.20.1",
        "1.8",
        "1.19.4",
        "1.12.2",
    ],
)
def test_stable_versions(version_string: str) -> None:
    assert is_stable_version(version_string) is True


@pytest.mark.parametrize(
    "version_string",
    [
        "1.21-pre1",
        "1.21-pre2",
        "1.21-Pre1",
        "1.21-rc1",
        "1.21-RC1",
        "1.21-snapshot1",
        "1.21-SNAPSHOT1",
        "24w13a",
        "25w02a",
        "23w07a",
    ],
)
def test_prerelease_versions(version_string: str) -> None:
    assert is_stable_version(version_string) is False

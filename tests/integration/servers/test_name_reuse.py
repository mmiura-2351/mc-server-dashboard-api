"""End-to-end coverage for the core goal of #429: a server name freed by
deletion can be reused.

Before the fix, soft-delete left ``servers/{name}`` on disk, so creating a
second server with the same name failed at the directory-existence guard in
``ServerFileSystemService.create_server_directory`` even though the DB
uniqueness check (which excludes soft-deleted rows) passed.

This drives the real API create -> delete -> create cycle, so it also
guards the ordering of archive-then-repoint inside ``delete_server``.
"""

import shutil
from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient

# The create endpoint triggers real Java discovery inside
# MinecraftServerManager — skip without a JRE (parity with
# ``test_port_conflicts.py``).
pytestmark = [pytest.mark.requires_java, pytest.mark.slow]


def _seed_version(db):
    from app.core.datetime_utils import utcnow
    from app.versions.models import MinecraftVersion

    db.add(
        MinecraftVersion(
            server_type="vanilla",
            version="1.21.6",
            download_url="https://launcher.mojang.com/v1/objects/test.jar",
            release_date=utcnow(),
            is_stable=True,
            is_active=True,
        )
    )
    db.commit()


def _create_payload(name: str) -> dict:
    return {
        "name": name,
        "description": "name-reuse e2e",
        "minecraft_version": "1.21.6",
        "server_type": "vanilla",
        "max_memory": 1024,
        "max_players": 20,
    }


class TestServerNameReuseAfterDeletion:
    def test_name_can_be_reused_after_delete(
        self, client: TestClient, admin_headers, db, admin_user
    ):
        from unittest.mock import patch

        _seed_version(db)
        name = "reuse-me"
        created_dirs: list[Path] = []
        # Ids whose directory gets archived by a delete in this test, so
        # cleanup can target only the archives this test produced rather
        # than wiping every ``servers/.archived/*`` (which may hold real
        # archived servers in a developer's working tree).
        archived_ids: list[int] = []

        try:
            with (
                patch(
                    "app.versions.application.jar_cache_manager."
                    "jar_cache_manager.get_or_download_jar"
                ) as mock_cache,
                patch(
                    "app.versions.application.jar_cache_manager."
                    "jar_cache_manager.copy_jar_to_server"
                ) as mock_copy,
            ):
                mock_cache.return_value = "/cache/test-vanilla-1.21.6.jar"
                mock_copy.return_value = "/server/server.jar"

                # 1) Create the first server and confirm its directory exists.
                first = client.post(
                    "/api/v1/servers/",
                    headers=admin_headers,
                    json=_create_payload(name),
                )
                assert first.status_code == status.HTTP_201_CREATED, first.text
                first_body = first.json()
                first_dir = Path(first_body["directory_path"])
                created_dirs.append(first_dir)
                assert first_dir.exists()

                # 2) Delete it — the directory should be archived away so the
                #    original path is freed.
                deleted = client.delete(
                    f"/api/v1/servers/{first_body['id']}", headers=admin_headers
                )
                assert deleted.status_code == status.HTTP_204_NO_CONTENT
                assert not first_dir.exists()
                archived_ids.append(first_body["id"])

                # 3) Create a *second* server with the same name — this is the
                #    behaviour #429 is about and must now succeed.
                second = client.post(
                    "/api/v1/servers/",
                    headers=admin_headers,
                    json=_create_payload(name),
                )
                assert second.status_code == status.HTTP_201_CREATED, second.text
                second_body = second.json()
                assert second_body["name"] == name
                assert second_body["id"] != first_body["id"]
                second_dir = Path(second_body["directory_path"])
                created_dirs.append(second_dir)
                assert second_dir.exists()
        finally:
            archive_root = Path("servers/.archived")
            for sid in archived_ids:
                for d in archive_root.glob(f"{sid}_*"):
                    shutil.rmtree(d, ignore_errors=True)
            for d in created_dirs:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)

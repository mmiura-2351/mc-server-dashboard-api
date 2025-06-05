import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.servers.models import Server
from app.types import FileType
from app.users.models import User


class FileManagementService:
    def __init__(self):
        self.allowed_extensions = {
            "config": [".properties", ".yml", ".yaml", ".json", ".txt", ".conf"],
            "world": [".dat", ".dat_old", ".mca", ".mcr"],
            "plugin": [".jar"],
            "mod": [".jar"],
            "log": [".log", ".gz"],
        }
        self.restricted_files = [
            "server.jar",
            "eula.txt",
            "ops.json",
            "whitelist.json",
            "banned-players.json",
            "banned-ips.json",
        ]

    async def get_server_files(
        self,
        server_id: int,
        path: str = "",
        file_type: Optional[FileType] = None,
        db: Session = None,
    ) -> List[Dict[str, Any]]:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        if not server_path.exists():
            raise HTTPException(status_code=404, detail="Server directory not found")

        target_path = server_path / path
        if not self._is_safe_path(server_path, target_path):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        files = []
        if target_path.is_dir():
            for item in target_path.iterdir():
                file_info = await self._get_file_info(item, server_path)
                if file_type is None or file_info["type"] == file_type:
                    files.append(file_info)
        else:
            file_info = await self._get_file_info(target_path, server_path)
            files.append(file_info)

        return sorted(files, key=lambda x: (x["is_directory"], x["name"]))

    async def read_file(
        self,
        server_id: int,
        file_path: str,
        encoding: str = "utf-8",
        db: Session = None,
    ) -> str:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        target_file = server_path / file_path

        if not self._is_safe_path(server_path, target_file):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_file.exists() or target_file.is_dir():
            raise HTTPException(status_code=404, detail="File not found")

        if not self._is_readable_file(target_file):
            raise HTTPException(status_code=403, detail="File type not supported")

        try:
            async with aiofiles.open(target_file, mode="r", encoding=encoding) as f:
                content = await f.read()
            return content
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400, detail="Unable to decode file with specified encoding"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

    async def write_file(
        self,
        server_id: int,
        file_path: str,
        content: str,
        encoding: str = "utf-8",
        create_backup: bool = True,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        target_file = server_path / file_path

        if not self._is_safe_path(server_path, target_file):
            raise HTTPException(status_code=403, detail="Access denied")

        if target_file.name in self.restricted_files and user.role.value != "admin":
            raise HTTPException(
                status_code=403, detail="Insufficient permissions to edit this file"
            )

        if not self._is_writable_file(target_file):
            raise HTTPException(
                status_code=403, detail="File type not supported for editing"
            )

        target_file.parent.mkdir(parents=True, exist_ok=True)

        if create_backup and target_file.exists():
            await self._create_file_backup(target_file)

        try:
            async with aiofiles.open(target_file, mode="w", encoding=encoding) as f:
                await f.write(content)

            file_info = await self._get_file_info(target_file, server_path)
            return {
                "message": "File updated successfully",
                "file": file_info,
                "backup_created": create_backup and target_file.exists(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")

    async def delete_file(
        self,
        server_id: int,
        file_path: str,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, str]:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        target_path = server_path / file_path

        if not self._is_safe_path(server_path, target_path):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="File or directory not found")

        if target_path.name in self.restricted_files and user.role.value != "admin":
            raise HTTPException(
                status_code=403, detail="Insufficient permissions to delete this file"
            )

        try:
            if target_path.is_dir():
                shutil.rmtree(target_path)
                return {"message": f"Directory '{file_path}' deleted successfully"}
            else:
                target_path.unlink()
                return {"message": f"File '{file_path}' deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error deleting file: {str(e)}")

    async def upload_file(
        self,
        server_id: int,
        file: UploadFile,
        destination_path: str = "",
        extract_if_archive: bool = False,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        target_dir = server_path / destination_path

        if not self._is_safe_path(server_path, target_dir):
            raise HTTPException(status_code=403, detail="Access denied")

        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / file.filename

        if target_file.name in self.restricted_files and user.role.value != "admin":
            raise HTTPException(
                status_code=403, detail="Insufficient permissions to upload this file"
            )

        try:
            async with aiofiles.open(target_file, "wb") as f:
                content = await file.read()
                await f.write(content)

            result = {
                "message": f"File '{file.filename}' uploaded successfully",
                "file": await self._get_file_info(target_file, server_path),
                "extracted_files": [],
            }

            if extract_if_archive and file.filename.endswith((".zip", ".jar")):
                extracted_files = await self._extract_archive(target_file, target_dir)
                result["extracted_files"] = extracted_files
                result["message"] += f" and extracted {len(extracted_files)} files"

            return result
        except Exception as e:
            if target_file.exists():
                target_file.unlink()
            raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")

    async def download_file(
        self,
        server_id: int,
        file_path: str,
        db: Session = None,
    ) -> Tuple[Path, str]:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        target_path = server_path / file_path

        if not self._is_safe_path(server_path, target_path):
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if target_path.is_dir():
            zip_path = await self._create_directory_archive(target_path)
            return zip_path, f"{target_path.name}.zip"
        else:
            return target_path, target_path.name

    async def create_directory(
        self,
        server_id: int,
        directory_path: str,
        user: User = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        server_path = Path(f"servers/{server.name}")
        target_dir = server_path / directory_path

        if not self._is_safe_path(server_path, target_dir):
            raise HTTPException(status_code=403, detail="Access denied")

        if target_dir.exists():
            raise HTTPException(status_code=409, detail="Directory already exists")

        try:
            target_dir.mkdir(parents=True)
            file_info = await self._get_file_info(target_dir, server_path)
            return {
                "message": f"Directory '{directory_path}' created successfully",
                "directory": file_info,
            }
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error creating directory: {str(e)}"
            )

    def _is_safe_path(self, base_path: Path, target_path: Path) -> bool:
        try:
            target_path.resolve().relative_to(base_path.resolve())
            return True
        except ValueError:
            return False

    def _is_readable_file(self, file_path: Path) -> bool:
        if file_path.suffix.lower() in [
            ext for exts in self.allowed_extensions.values() for ext in exts
        ]:
            return True
        return file_path.stat().st_size < 10 * 1024 * 1024  # 10MB limit for unknown files

    def _is_writable_file(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in [
            ".properties",
            ".yml",
            ".yaml",
            ".json",
            ".txt",
            ".conf",
        ]

    async def _get_file_info(self, path: Path, server_path: Path) -> Dict[str, Any]:
        stat = path.stat()
        relative_path = path.relative_to(server_path)

        file_type = self._determine_file_type(path)

        return {
            "name": path.name,
            "path": str(relative_path),
            "type": file_type,
            "is_directory": path.is_dir(),
            "size": stat.st_size if not path.is_dir() else None,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "permissions": {
                "readable": self._is_readable_file(path) if not path.is_dir() else True,
                "writable": self._is_writable_file(path) if not path.is_dir() else True,
                "restricted": path.name in self.restricted_files,
            },
        }

    def _determine_file_type(self, path: Path) -> FileType:
        if path.is_dir():
            return FileType.directory

        suffix = path.suffix.lower()
        name = path.name.lower()

        if suffix in self.allowed_extensions["config"] or name in [
            "server.properties",
            "eula.txt",
        ]:
            return FileType.config
        elif suffix in self.allowed_extensions["plugin"]:
            return FileType.plugin
        elif suffix in self.allowed_extensions["mod"]:
            return FileType.mod
        elif suffix in self.allowed_extensions["log"]:
            return FileType.log
        elif suffix in self.allowed_extensions["world"] or "world" in str(path.parent):
            return FileType.world
        else:
            return FileType.other

    async def _create_file_backup(self, file_path: Path) -> None:
        backup_dir = file_path.parent / ".backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.name}.{timestamp}.bak"
        backup_path = backup_dir / backup_name

        shutil.copy2(file_path, backup_path)

    async def _extract_archive(self, archive_path: Path, extract_to: Path) -> List[str]:
        extracted_files = []
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                if self._is_safe_path(extract_to, extract_to / member):
                    zip_ref.extract(member, extract_to)
                    extracted_files.append(member)
        return extracted_files

    async def _create_directory_archive(self, directory: Path) -> Path:
        temp_dir = Path(tempfile.gettempdir())
        zip_path = (
            temp_dir / f"{directory.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(directory)
                    zip_file.write(file_path, arcname)

        return zip_path

    async def search_files(
        self,
        server_id: int,
        query: str,
        file_type: Optional[FileType] = None,
        include_content: bool = False,
        max_results: int = 50,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Search for files in server directory"""
        import re
        import time

        start_time = time.time()

        # Get all files first
        all_files = await self.get_server_files(
            server_id=server_id,
            path="",
            file_type=file_type,
            db=db,
        )

        results = []
        pattern = re.compile(query, re.IGNORECASE)

        for file_info in all_files:
            matches = []
            match_count = 0

            # Search in filename
            if pattern.search(file_info["name"]):
                match_count += 1
                matches.append(f"Filename: {file_info['name']}")

            # Search in file content if requested and file is readable
            if (
                include_content
                and not file_info["is_directory"]
                and file_info["permissions"]["readable"]
            ):
                try:
                    content = await self.read_file(
                        server_id=server_id,
                        file_path=file_info["path"],
                        db=db,
                    )

                    content_matches = []
                    for i, line in enumerate(content.split("\n"), 1):
                        if pattern.search(line):
                            content_matches.append(f"Line {i}: {line.strip()}")
                            match_count += 1

                    matches.extend(content_matches[:10])  # Limit content matches

                except Exception:
                    pass  # Skip files that can't be read

            if match_count > 0:
                results.append(
                    {
                        "file": file_info,
                        "matches": matches,
                        "match_count": match_count,
                    }
                )

            if len(results) >= max_results:
                break

        search_time_ms = int((time.time() - start_time) * 1000)

        return {
            "results": results,
            "query": query,
            "total_results": len(results),
            "search_time_ms": search_time_ms,
        }

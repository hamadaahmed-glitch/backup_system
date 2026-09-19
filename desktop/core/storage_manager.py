"""
Storage Hierarchy and Atomicity Manager.
Guarantees directory layouts, manages mutual exclusion locks,
and handles atomic directory promotion (.partial -> complete).
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StorageManager:
    """Controls the local filesystem structure where client backups reside."""

    PARTIAL_SUFFIX = ".partial"

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve()
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
            # Test write permission
            test_file = self.storage_root / ".write_test"
            test_file.touch()
            test_file.unlink()
        except PermissionError as e:
            raise PermissionError(
                f"Cannot write to '{self.storage_root}'. Permission denied.\n"
                f"Fix permissions using: sudo mkdir -p {self.storage_root} && sudo chown -R $USER:$USER {self.storage_root}\n"
                f"Or use a directory inside your home folder (e.g. ~/Backups)."
            ) from e

    def get_client_dir(self, client_hostname: str) -> Path:
        client_path = self.storage_root / client_hostname
        client_path.mkdir(parents=True, exist_ok=True)
        return client_path

    def acquire_lock(self, client_hostname: str) -> bool:
        client_dir = self.get_client_dir(client_hostname)
        lock_file = client_dir / ".backup.lock"

        if lock_file.exists():
            try:
                with open(lock_file, "r", encoding="utf-8") as f:
                    pid = f.read().strip()
                logger.warning(
                    "Job already locked for client %s by PID: %s", client_hostname, pid
                )
            except Exception:
                pass
            return False

        try:
            with open(lock_file, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return True
        except OSError as e:
            logger.error("Failed to write lockfile for %s: %s", client_hostname, e)
            return False

    def release_lock(self, client_hostname: str) -> None:
        lock_file = self.get_client_dir(client_hostname) / ".backup.lock"
        if lock_file.exists():
            try:
                lock_file.unlink()
            except OSError as e:
                logger.error("Failed to release lock file %s: %s", lock_file, e)

    def get_staging_directory(self, client_hostname: str, backup_id: str) -> Path:
        client_dir = self.get_client_dir(client_hostname)
        staging_dir = client_dir / f"{backup_id}{self.PARTIAL_SUFFIX}"
        staging_dir.mkdir(parents=True, exist_ok=True)
        return staging_dir

    def promote_to_complete(self, staging_dir: Path) -> Path:
        staging_path = Path(staging_dir).resolve()
        if not staging_path.name.endswith(self.PARTIAL_SUFFIX):
            return staging_path

        final_name = staging_path.name[: -len(self.PARTIAL_SUFFIX)]
        final_destination = staging_path.parent / final_name

        if final_destination.exists():
            logger.warning("Target completed path %s exists; replacing.", final_destination)
            shutil.rmtree(final_destination)

        staging_path.rename(final_destination)
        logger.info("Promoted %s -> %s", staging_path.name, final_destination.name)
        return final_destination

    def write_metadata(self, backup_dir: Path, metadata: Dict[str, Any]) -> Path:
        target_dir = Path(backup_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        meta_file = target_dir / "backup_metadata.json"

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        return meta_file

    def read_metadata(self, backup_dir: Path) -> Optional[Dict[str, Any]]:
        meta_file = Path(backup_dir) / "backup_metadata.json"
        if not meta_file.is_file():
            return None
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Could not parse metadata at %s: %s", meta_file, e)
            return None
"""
Backup Metadata Model.
Encapsulates runtime details, filesystem parameters, and audit metrics.
Provides serialization to and from JSON files.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .constants import APP_VERSION, BackupStatus


@dataclass
class BackupMetadata:
    """Represents data descriptors for a single backup job."""
    backup_id: str
    client_hostname: str
    client_username: str
    source_partition: str
    source_mountpoint: str
    filesystem_type: str
    filesystem_uuid: str
    storage_path: str
    bytes_transferred: int
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0
    status: str = str(BackupStatus.IN_PROGRESS)
    app_version: str = APP_VERSION
    integrity_verified: bool = False
    notes: Optional[str] = None

    @classmethod
    def create_new(
        cls,
        client_hostname: str,
        client_username: str,
        source_partition: str,
        source_mountpoint: str,
        filesystem_type: str,
        filesystem_uuid: str,
        storage_path: str,
    ) -> "BackupMetadata":
        """Generates an initial metadata instance for an active backup run."""
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y-%m-%d-%H%M%S")
        backup_id = f"{client_hostname}-{timestamp_str}"

        return cls(
            backup_id=backup_id,
            client_hostname=client_hostname,
            client_username=client_username,
            source_partition=source_partition,
            source_mountpoint=source_mountpoint,
            filesystem_type=filesystem_type,
            filesystem_uuid=filesystem_uuid,
            storage_path=storage_path,
            bytes_transferred=0,
            started_at=timestamp.isoformat(),
            status=str(BackupStatus.IN_PROGRESS),
        )

    def mark_completed(
        self,
        bytes_transferred: int,
        duration_seconds: float,
        integrity_verified: bool = True,
        notes: Optional[str] = None,
    ) -> None:
        """Transitions the record to COMPLETED state."""
        self.bytes_transferred = bytes_transferred
        self.duration_seconds = round(duration_seconds, 2)
        self.completed_at = datetime.now().isoformat()
        self.status = str(BackupStatus.COMPLETED)
        self.integrity_verified = integrity_verified
        if notes:
            self.notes = notes

    def mark_failed(self, notes: str) -> None:
        """Transitions the record to FAILED state."""
        self.completed_at = datetime.now().isoformat()
        self.status = str(BackupStatus.FAILED)
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        """Converts dataclass to standard Python dictionary."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serializes instance to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupMetadata":
        """Constructs an instance from a dictionary."""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "BackupMetadata":
        """Constructs an instance from raw JSON text."""
        return cls.from_dict(json.loads(json_str))

    def save_to_file(self, target_path: Path) -> Path:
        """Saves metadata to disk."""
        target_path = Path(target_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return target_path

    @classmethod
    def load_from_file(cls, file_path: Path) -> "BackupMetadata":
        """Loads and parses metadata JSON from a file."""
        with open(file_path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())
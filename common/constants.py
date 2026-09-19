"""
System-wide Constants and Enumerations.
Defines application defaults, network parameters, supported filesystems,
and operational backup status codes.
"""

from enum import Enum
from typing import Set

APP_NAME: str = "LinuxPartitionBackup"
APP_VERSION: str = "1.0.0"

# Networking & Transfer Defaults
DEFAULT_SSH_PORT: int = 22
DEFAULT_CONNECT_TIMEOUT: int = 5  # seconds
DEFAULT_SAFETY_MARGIN: float = 0.10  # 10% storage buffer headroom

# Filesystem & Storage
SUPPORTED_FILESYSTEMS: Set[str] = {"ext4", "btrfs", "xfs", "ext3", "ext2"}
PARTIAL_SUFFIX: str = ".partial"
LOCK_FILENAME: str = ".backup.lock"
METADATA_FILENAME: str = "backup_metadata.json"
DATABASE_FILENAME: str = "backup_catalog.db"

# Rsync Optimization Flags
DEFAULT_RSYNC_EXCLUDES = [
    "/proc/*",
    "/sys/*",
    "/dev/*",
    "/run/*",
    "/tmp/*",
    "/mnt/*",
    "/media/*",
    "/lost+found",
    ".rsync-partial",
]


class BackupStatus(str, Enum):
    """Operational states for backup jobs."""
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    PRUNED = "PRUNED"

    def __str__(self) -> str:
        return self.value
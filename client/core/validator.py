"""
Pre-Flight Validation Engine.
Performs verification of host network, destination capacity, 
permissions, and binaries prior to initiating rsync operations.
"""

import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .ssh_client import SSHClient
from .system_detect import PartitionInfo

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Holds the pre-flight checks assessment."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    source_used_bytes: int = 0
    destination_available_bytes: int = 0


class SystemValidator:
    """Executes pre-transfer validation routines."""

    def __init__(self, ssh_client: SSHClient) -> None:
        self.ssh_client = ssh_client

    @staticmethod
    def is_host_reachable(host: str, port: int = 22, timeout: float = 3.0) -> bool:
        """Checks raw TCP socket connectivity to the target host and port."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, OSError):
            return False

    def validate_pre_flight(
        self,
        partition: PartitionInfo,
        destination_path: str,
        safety_margin_ratio: float = 0.10,
    ) -> ValidationResult:
        """
        Conducts a complete health check before permitting rsync to start:
        1. Checks source readability and mount status.
        2. Validates network connectivity.
        3. Tests remote SSH access and authentications.
        4. Verifies remote rsync installation.
        5. Computes disk capacity differences including safety margins.
        """
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Source Mount Check
        if not partition.is_mounted or not partition.mountpoint:
            errors.append(f"Partition {partition.device_path} is not mounted.")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        mount_path = Path(partition.mountpoint)
        if not mount_path.is_dir() or not mount_path.exists():
            errors.append(f"Mountpoint {partition.mountpoint} does not exist as a directory.")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # Check source filesystem
        if partition.fstype.lower() not in ["ext4", "btrfs", "xfs"]:
            warnings.append(
                f"Filesystem type is '{partition.fstype}'. Linux special permissions "
                "might encounter incompatibilities if not an ext-family or native Linux fs."
            )

        # 2. Raw Network Check
        if not self.is_host_reachable(self.ssh_client.host, self.ssh_client.port):
            errors.append(f"Target host {self.ssh_client.host}:{self.ssh_client.port} is unreachable.")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 3. SSH Auth Check
        ssh_ok, ssh_msg = self.ssh_client.test_connection()
        if not ssh_ok:
            errors.append(f"SSH authentication check failed: {ssh_msg}")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 4. Remote rsync installation check
        if not self.ssh_client.check_remote_rsync_installed():
            errors.append("The 'rsync' binary was not found on the remote Desktop server.")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 5. Remote Storage Capacity Check
        source_used = partition.used_bytes
        dest_avail = self.ssh_client.get_remote_free_space(destination_path)

        if dest_avail is None:
            errors.append(f"Could not retrieve available space for remote directory '{destination_path}'.")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        required_bytes = int(source_used * (1.0 + safety_margin_ratio))

        if dest_avail < required_bytes:
            errors.append(
                f"Insufficient disk space on Desktop. "
                f"Source requires: {source_used / (1024**3):.2f} GB (+{int(safety_margin_ratio*100)}% margin: "
                f"{required_bytes / (1024**3):.2f} GB). "
                f"Available on remote: {dest_avail / (1024**3):.2f} GB."
            )

        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            warnings=warnings,
            source_used_bytes=source_used,
            destination_available_bytes=dest_avail,
        )
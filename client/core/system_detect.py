"""
System Partition and Filesystem Detection Engine.
Filters out virtual snap loop devices, detects physical partitions,
and handles auto-mounting for unmounted partitions.
"""

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PartitionInfo:
    """Immutable data container representing partition details."""
    name: str
    device_path: str
    mountpoint: Optional[str]
    fstype: str
    uuid: str
    total_bytes: int
    used_bytes: int
    available_bytes: int

    @property
    def is_mounted(self) -> bool:
        return self.mountpoint is not None and len(self.mountpoint) > 0


class SystemDetector:
    """Detects storage layout, filesystem attributes, and space usage."""

    def __init__(self) -> None:
        self._ensure_linux_dependencies()

    @staticmethod
    def _ensure_linux_dependencies() -> None:
        required_tools = ["lsblk", "findmnt", "df"]
        for tool in required_tools:
            if shutil.which(tool) is None:
                raise EnvironmentError(f"Required system utility '{tool}' was not found in PATH.")

    def list_block_devices(self, include_loop: bool = False) -> List[PartitionInfo]:
        """
        Scans the host system using `lsblk`.
        Ignores virtual snap loop devices by default.
        """
        cmd = [
            "lsblk",
            "--json",
            "--bytes",
            "-o",
            "NAME,PATH,MOUNTPOINT,FSTYPE,UUID,SIZE,TYPE",
        ]
        # Exclude loop devices at lsblk level (major number 7)
        if not include_loop:
            cmd.extend(["-e", "7"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as err:
            logger.error("Failed to query block devices via lsblk: %s", err)
            return []

        partitions: List[PartitionInfo] = []
        devices = data.get("blockdevices", [])

        def parse_node(node: Dict) -> None:
            name = node.get("name", "")
            path = node.get("path", f"/dev/{name}")
            mountpoint = node.get("mountpoint")
            fstype = node.get("fstype") or "unknown"
            uuid = node.get("uuid") or ""
            size = node.get("size") or 0
            dev_type = node.get("type", "")

            # Ignore loop devices or squashfs snap filesystems
            if not include_loop and (dev_type == "loop" or fstype == "squashfs" or name.startswith("loop")):
                return

            total_bytes = int(size)
            used_bytes = 0
            avail_bytes = 0

            # If mounted, fetch real used/free numbers
            if mountpoint and Path(mountpoint).exists():
                try:
                    usage = shutil.disk_usage(mountpoint)
                    total_bytes = usage.total
                    used_bytes = usage.used
                    avail_bytes = usage.free
                except OSError as e:
                    logger.warning("Could not read disk usage for %s: %s", mountpoint, e)

            if path and total_bytes > 0:
                partitions.append(
                    PartitionInfo(
                        name=name,
                        device_path=path,
                        mountpoint=mountpoint,
                        fstype=fstype,
                        uuid=uuid,
                        total_bytes=total_bytes,
                        used_bytes=used_bytes,
                        available_bytes=avail_bytes,
                    )
                )

            for child in node.get("children", []):
                parse_node(child)

        for dev in devices:
            parse_node(dev)

        return partitions

    def get_partition_by_path_or_mount(self, identifier: str) -> Optional[PartitionInfo]:
        """Locates a partition by its device path or mount point."""
        resolved_identifier = str(Path(identifier).resolve())
        partitions = self.list_block_devices(include_loop=False)

        for part in partitions:
            if part.device_path == identifier or part.device_path == resolved_identifier:
                return part
            if part.mountpoint and Path(part.mountpoint).resolve() == Path(resolved_identifier):
                return part

        return None

    @staticmethod
    def mount_partition(device_path: str) -> Tuple[bool, str]:
        """
        Mounts an unmounted partition.
        Tries udisksctl first (user-space, no root needed), then falls back to mount.
        Returns: (success_bool, mountpoint_path_or_error)
        """
        # 1. Try udisksctl (standard on Ubuntu Desktop)
        if shutil.which("udisksctl"):
            res = subprocess.run(
                ["udisksctl", "mount", "-b", device_path],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                # Output format: "Mounted /dev/nvme0n1p2 at /media/user/LABEL."
                out = res.stdout.strip()
                if " at " in out:
                    mountpoint = out.split(" at ")[-1].rstrip(".")
                    return True, mountpoint

        # 2. Fallback: manual mount to /mnt/backup_source
        fallback_dir = Path("/mnt/backup_source")
        try:
            fallback_dir.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                ["sudo", "mount", "-o", "ro", device_path, str(fallback_dir)],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return True, str(fallback_dir)
            return False, res.stderr.strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    def unmount_partition(mountpoint_or_device: str) -> bool:
        """Unmounts a temporarily mounted partition cleanly."""
        if shutil.which("udisksctl") and mountpoint_or_device.startswith("/dev/"):
            res = subprocess.run(["udisksctl", "unmount", "-b", mountpoint_or_device], capture_output=True)
            if res.returncode == 0:
                return True

        res = subprocess.run(["sudo", "umount", mountpoint_or_device], capture_output=True)
        return res.returncode == 0
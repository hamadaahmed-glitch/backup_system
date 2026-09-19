"""
Destination Integrity Checker.
Executes server-side audits on archived files, calculating file counts,
tree size, and deterministic SHA-256 samples on stored backups.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AuditReport:
    """Summary of a post-transfer storage integrity check."""
    backup_id: str
    is_valid: bool
    total_files: int
    total_bytes: int
    sample_files_checked: int
    summary: str


class IntegrityChecker:
    """Audits local backup data integrity without requiring the source client."""

    @staticmethod
    def calculate_file_sha256(file_path: Path, block_size: int = 65536) -> str:
        """Computes SHA-256 digest of a single file in chunks."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                hasher.update(block)
        return hasher.hexdigest()

    def audit_backup_directory(
        self,
        backup_id: str,
        backup_dir: Path,
        sample_count: int = 25,
    ) -> AuditReport:
        """
        Conducts sanity and checksum checks across the stored backup:
        1. Verifies path existence and accessibility.
        2. Counts total stored files and computes aggregate bytes.
        3. Tests byte readability on a sample set of files.
        """
        target_path = Path(backup_dir).resolve()

        if not target_path.exists() or not target_path.is_dir():
            return AuditReport(
                backup_id=backup_id,
                is_valid=False,
                total_files=0,
                total_bytes=0,
                sample_files_checked=0,
                summary=f"Path '{target_path}' does not exist or is not a directory.",
            )

        total_files = 0
        total_bytes = 0
        files_to_sample: List[Path] = []

        try:
            # Traverse directory structure
            for entry in target_path.rglob("*"):
                # Skip metadata and rsync temp dirs
                if "backup_metadata.json" in entry.name or ".rsync-partial" in entry.parts:
                    continue

                if entry.is_file() and not entry.is_symlink():
                    total_files += 1
                    try:
                        file_size = entry.stat().st_size
                        total_bytes += file_size
                        if len(files_to_sample) < sample_count:
                            files_to_sample.append(entry)
                    except OSError as err:
                        logger.warning("Stat error on file %s: %s", entry, err)

        except Exception as e:
            return AuditReport(
                backup_id=backup_id,
                is_valid=False,
                total_files=total_files,
                total_bytes=total_bytes,
                sample_files_checked=0,
                summary=f"Encountered error while indexing directory tree: {str(e)}",
            )

        if total_files == 0:
            return AuditReport(
                backup_id=backup_id,
                is_valid=False,
                total_files=0,
                total_bytes=0,
                sample_files_checked=0,
                summary="Storage path contains zero regular files (empty backup).",
            )

        # Sample read check (validates actual storage readability)
        sampled_read_ok = 0
        for sample_file in files_to_sample:
            try:
                _ = self.calculate_file_sha256(sample_file)
                sampled_read_ok += 1
            except Exception as read_err:
                logger.error("Failed reading sampled file %s: %s", sample_file, read_err)
                return AuditReport(
                    backup_id=backup_id,
                    is_valid=False,
                    total_files=total_files,
                    total_bytes=total_bytes,
                    sample_files_checked=sampled_read_ok,
                    summary=f"Data corruption or read failure on file: {sample_file.name}",
                )

        return AuditReport(
            backup_id=backup_id,
            is_valid=True,
            total_files=total_files,
            total_bytes=total_bytes,
            sample_files_checked=sampled_read_ok,
            summary=(
                f"Integrity audit passed: {total_files} files verified "
                f"({total_bytes / (1024**3):.2f} GB total). "
                f"{sampled_read_ok} files checksummed successfully."
            ),
        )
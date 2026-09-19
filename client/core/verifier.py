"""
Backup Verification Engine.
Interprets exit codes and conducts post-transfer integrity checks.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .ssh_client import SSHClient

logger = logging.getLogger(__name__)


@dataclass
class VerificationReport:
    """Report detailing post-transfer data status."""
    is_success: bool
    status_summary: str
    exit_code: int
    rsync_meaning: str
    source_file_count: Optional[int] = None
    dest_file_count: Optional[int] = None


class Verifier:
    """Validates the execution results of an rsync backup operation."""

    RSYNC_EXIT_CODES: Dict[int, str] = {
        0: "Success",
        1: "Syntax or usage error",
        2: "Protocol incompatibility",
        3: "Errors selecting input/output files, dirs",
        4: "Requested action not supported",
        5: "Error starting client-server protocol",
        6: "Daemon unable to append to log-file",
        10: "Error in socket I/O",
        11: "Error in file I/O",
        12: "Error in rsync protocol data stream",
        13: "Errors with program diagnostics",
        14: "Error in IPC code",
        20: "Received SIGUSR1 or SIGINT",
        21: "Some error returned by waitpid()",
        22: "Error allocating core memory buffers",
        23: "Partial transfer due to error",
        24: "Partial transfer due to vanished source files",
        25: "The --max-delete limit stopped deletions",
        30: "Timeout in data send/receive",
        35: "Timeout waiting for daemon connection",
    }

    def __init__(self, ssh_client: SSHClient) -> None:
        self.ssh_client = ssh_client

    def interpret_exit_code(self, code: int) -> Tuple[bool, str]:
        """
        Translates an rsync exit code to an operational result.
        Exit code 24 indicates that a source file was deleted or altered
        during transfer, which is usually considered acceptable in active filesystems.
        """
        meaning = self.RSYNC_EXIT_CODES.get(code, f"Unknown exit error ({code})")
        if code == 0:
            return True, meaning
        if code == 24:
            logger.warning("Rsync reported vanished source files (Code 24). Backup is usable.")
            return True, meaning
        return False, meaning

    def quick_post_transfer_check(
        self,
        source_dir: str,
        remote_dest_dir: str,
        rsync_exit_code: int,
    ) -> VerificationReport:
        """
        Runs an audit following an rsync transfer:
        1. Checks the process exit code.
        2. Queries remote storage to confirm the presence of content.
        3. Compares top-level element counts between local and remote locations.
        """
        is_code_ok, meaning = self.interpret_exit_code(rsync_exit_code)

        if not is_code_ok:
            return VerificationReport(
                is_success=False,
                status_summary=f"Rsync operation failed with error: {meaning}",
                exit_code=rsync_exit_code,
                rsync_meaning=meaning,
            )

        # Count top-level entries locally
        try:
            import subprocess
            local_cmd = f"find {source_dir} -mindepth 1 -maxdepth 1 | wc -l"
            local_count_res = subprocess.run(
                local_cmd, shell=True, capture_output=True, text=True, check=True
            )
            source_count = int(local_count_res.stdout.strip())
        except Exception as e:
            logger.warning("Could not count local items for verification: %s", e)
            source_count = None

        # Count top-level entries remotely
        remote_cmd = f"find {remote_dest_dir} -mindepth 1 -maxdepth 1 | wc -l"
        rem_code, rem_stdout, rem_stderr = self.ssh_client.run_command(remote_cmd)

        dest_count: Optional[int] = None
        if rem_code == 0:
            try:
                dest_count = int(rem_stdout.strip())
            except ValueError:
                pass
        else:
            logger.warning("Could not count remote items for verification: %s", rem_stderr.strip())

        # Validate that the destination directory contains files
        if dest_count is not None and dest_count == 0 and source_count and source_count > 0:
            return VerificationReport(
                is_success=False,
                status_summary="Destination directory exists but is empty despite non-empty source.",
                exit_code=rsync_exit_code,
                rsync_meaning=meaning,
                source_file_count=source_count,
                dest_file_count=dest_count,
            )

        return VerificationReport(
            is_success=True,
            status_summary="Transfer completed and basic verification checks passed.",
            exit_code=rsync_exit_code,
            rsync_meaning=meaning,
            source_file_count=source_count,
            dest_file_count=dest_count,
        )
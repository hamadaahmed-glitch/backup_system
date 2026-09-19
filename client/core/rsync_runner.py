"""
Rsync Subprocess Controller.
Supports both native Linux ext4 and Windows NTFS source partitions.
"""

import logging
import os
import select
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .progress_parser import ProgressParser, TransferProgress

logger = logging.getLogger(__name__)


@dataclass
class RsyncExecutionResult:
    exit_code: int
    was_interrupted: bool
    total_bytes_transferred: int
    error_message: Optional[str] = None


class RsyncRunner:
    def __init__(
        self,
        source_dir: str,
        dest_user: str,
        dest_host: str,
        dest_path: str,
        ssh_port: int = 22,
        identity_file: Optional[str] = None,
        compress: bool = False,
        dry_run: bool = False,
        is_ntfs: bool = False,
        exclude_patterns: Optional[List[str]] = None,
    ) -> None:
        self.source_dir = str(Path(source_dir).resolve())
        self.dest_user = dest_user
        self.dest_host = dest_host
        self.dest_path = dest_path
        self.ssh_port = ssh_port
        self.identity_file = identity_file
        self.compress = compress
        self.dry_run = dry_run
        self.is_ntfs = is_ntfs
        self.exclude_patterns = exclude_patterns or []

        self._process: Optional[subprocess.Popen] = None
        self._parser = ProgressParser()
        self._interrupted = False

    def _build_command(self) -> List[str]:
        formatted_source = self.source_dir if self.source_dir.endswith("/") else f"{self.source_dir}/"

        ssh_opts = f"ssh -p {self.ssh_port} -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
        if self.identity_file:
            ssh_opts += f" -i {shlex.quote(str(Path(self.identity_file).expanduser()))}"

        # Standard ext4 vs NTFS flags
        if self.is_ntfs:
            # NTFS doesn't support Linux POSIX ACLs (-A) or xattrs (-X)
            flags = "-rltD"
        else:
            flags = "-aHAXS"

        cmd = [
            "rsync",
            flags,
            "--numeric-ids",
            "--info=progress2",
            "--partial-dir=.rsync-partial",
            "-e", ssh_opts,
        ]

        if self.compress:
            cmd.append("-z")

        if self.dry_run:
            cmd.append("--dry-run")

        # Exclude Windows system lockfiles on NTFS
        if self.is_ntfs:
            cmd.extend([
                "--exclude", "$RECYCLE.BIN",
                "--exclude", "System Volume Information",
                "--exclude", "pagefile.sys",
                "--exclude", "hiberfil.sys",
            ])

        for pattern in self.exclude_patterns:
            cmd.extend(["--exclude", pattern])

        remote_target = f"{self.dest_user}@{self.dest_host}:{self.dest_path}"
        cmd.extend([formatted_source, remote_target])

        return cmd

    def execute(
        self,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> RsyncExecutionResult:
        cmd = self._build_command()
        logger.info("Starting rsync transfer from '%s' to '%s'", self.source_dir, self.dest_path)
        logger.debug("Rsync command: %s", " ".join(cmd))

        self._interrupted = False
        last_progress_bytes = 0
        stderr_buffer: List[str] = []

        orig_sigint = signal.getsignal(signal.SIGINT)
        orig_sigterm = signal.getsignal(signal.SIGTERM)

        def _handle_interrupt(signum, frame):
            logger.warning("Interrupted by user. Terminating rsync cleanly...")
            self._interrupted = True
            self.terminate()

        signal.signal(signal.SIGINT, _handle_interrupt)
        signal.signal(signal.SIGTERM, _handle_interrupt)

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                universal_newlines=False,
            )

            stdout_fd = self._process.stdout.fileno()
            stderr_fd = self._process.stderr.fileno()
            line_buffer = bytearray()

            while self._process.poll() is None:
                readable, _, _ = select.select([stdout_fd, stderr_fd], [], [], 0.2)
                for fd in readable:
                    if fd == stdout_fd:
                        chunk = os.read(stdout_fd, 1024)
                        if not chunk:
                            continue
                        for byte in chunk:
                            char = chr(byte)
                            if char in ("\r", "\n"):
                                line = line_buffer.decode("utf-8", errors="replace")
                                line_buffer.clear()
                                parsed = self._parser.parse_line(line)
                                if parsed:
                                    last_progress_bytes = parsed.bytes_transferred
                                    if progress_callback:
                                        progress_callback(parsed)
                            else:
                                line_buffer.append(byte)

                    elif fd == stderr_fd:
                        err_chunk = os.read(stderr_fd, 1024)
                        if err_chunk:
                            err_text = err_chunk.decode("utf-8", errors="replace")
                            stderr_buffer.append(err_text)

            remaining_stdout = self._process.stdout.read().decode("utf-8", errors="replace")
            for line in remaining_stdout.splitlines():
                parsed = self._parser.parse_line(line)
                if parsed:
                    last_progress_bytes = parsed.bytes_transferred
                    if progress_callback:
                        progress_callback(parsed)

            remaining_stderr = self._process.stderr.read().decode("utf-8", errors="replace")
            if remaining_stderr:
                stderr_buffer.append(remaining_stderr)

            exit_code = self._process.returncode

        finally:
            signal.signal(signal.SIGINT, orig_sigint)
            signal.signal(signal.SIGTERM, orig_sigterm)

        error_message = "".join(stderr_buffer).strip() if stderr_buffer else None

        return RsyncExecutionResult(
            exit_code=exit_code,
            was_interrupted=self._interrupted,
            total_bytes_transferred=last_progress_bytes,
            error_message=error_message,
        )

    def terminate(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            except ProcessLookupError:
                pass
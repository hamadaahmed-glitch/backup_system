"""
OpenSSH Controller.
Executes remote verification commands over the native system SSH binary.
"""

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class SSHClient:
    """Manages secure communication and command execution on the remote desktop."""

    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        identity_file: Optional[str] = None,
        connect_timeout: int = 5,
    ) -> None:
        self.host = host
        self.user = user
        self.port = port
        self.identity_file = identity_file
        self.connect_timeout = connect_timeout

    def _build_base_ssh_command(self) -> list:
        """Constructs base OpenSSH arguments with safety parameters."""
        cmd = [
            "ssh",
            "-p", str(self.port),
            "-o", f"ConnectTimeout={self.connect_timeout}",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        if self.identity_file:
            key_path = Path(self.identity_file).expanduser().resolve()
            if not key_path.exists():
                raise FileNotFoundError(f"SSH private key file not found: {key_path}")
            cmd.extend(["-i", str(key_path)])

        cmd.append(f"{self.user}@{self.host}")
        return cmd

    def test_connection(self) -> Tuple[bool, str]:
        """Validates that the remote target is reachable and accepts the SSH session."""
        cmd = self._build_base_ssh_command() + ["exit", "0"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=self.connect_timeout + 2)
            if res.returncode == 0:
                return True, "SSH Connection successful."
            return False, f"SSH Connection failed (Code {res.returncode}): {res.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return False, f"SSH connection to {self.host}:{self.port} timed out."
        except Exception as e:
            return False, f"Unexpected SSH execution error: {str(e)}"

    def run_command(self, remote_command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """
        Executes a command string remotely on the desktop via SSH.
        Returns: (exit_code, stdout, stderr)
        """
        cmd = self._build_base_ssh_command() + [remote_command]
        try:
            logger.debug("Executing remote command via SSH: %s", remote_command)
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, res.stdout, res.stderr
        except subprocess.TimeoutExpired:
            logger.error("Remote command timed out after %d seconds.", timeout)
            return 124, "", "Command timed out."
        except Exception as e:
            logger.error("Failed to run remote command: %s", e)
            return 1, "", str(e)

    def get_remote_free_space(self, remote_directory_path: str) -> Optional[int]:
        """
        Queries the available space in bytes on the destination directory.
        Uses `df -B1` on the remote side.
        """
        # Ensure path is safely escaped
        safe_path = shlex.quote(remote_directory_path)
        # Execute remote df on the targeted directory
        remote_cmd = f"mkdir -p {safe_path} && df -B1 --output=avail {safe_path} | tail -n 1"
        code, stdout, stderr = self.run_command(remote_cmd)

        if code != 0:
            logger.error("Failed to fetch remote storage space: %s", stderr.strip())
            return None

        output = stdout.strip()
        try:
            return int(output)
        except ValueError:
            logger.error("Unable to parse remote free bytes from output: '%s'", output)
            return None

    def check_remote_rsync_installed(self) -> bool:
        """Verifies that `rsync` binary is installed and executable on the desktop."""
        code, stdout, _ = self.run_command("which rsync")
        return code == 0 and len(stdout.strip()) > 0
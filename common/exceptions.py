"""
Custom Exception Hierarchy.
Provides categorized error classes for failure handling, retry logic,
and informative logging.
"""

from typing import Optional


class BackupSystemError(Exception):
    """Base exception for all errors within the backup application."""
    def __init__(self, message: str, details: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (Details: {self.details})"
        return self.message


class NetworkError(BackupSystemError):
    """Raised when host reachability or TCP sockets fail."""
    pass


class AuthenticationError(BackupSystemError):
    """Raised when SSH keys or credentials are rejected by the target server."""
    pass


class DestinationDiskFullError(BackupSystemError):
    """Raised when available space on destination is insufficient."""
    def __init__(
        self,
        message: str,
        required_bytes: int,
        available_bytes: int,
    ) -> None:
        super().__init__(message)
        self.required_bytes = required_bytes
        self.available_bytes = available_bytes

    def __str__(self) -> str:
        req_gb = self.required_bytes / (1024**3)
        avail_gb = self.available_bytes / (1024**3)
        return f"{self.message} [Required: {req_gb:.2f} GB, Available: {avail_gb:.2f} GB]"


class SourcePartitionError(BackupSystemError):
    """Raised when source device is missing, unmounted, or unreadable."""
    pass


class RsyncExecutionError(BackupSystemError):
    """Raised when rsync process returns a non-zero exit code."""
    def __init__(self, message: str, exit_code: int, stderr_output: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr_output = stderr_output

    def __str__(self) -> str:
        return f"{self.message} (Exit Code: {self.exit_code}) | Stderr: {self.stderr_output}"


class VerificationError(BackupSystemError):
    """Raised when post-transfer integrity checks fail."""
    pass


class LockAcquisitionError(BackupSystemError):
    """Raised when a backup operation is already running for the target client."""
    pass
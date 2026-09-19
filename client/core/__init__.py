"""
Client Core Package

Exports core engines for discovery, validation, SSH communication,
rsync execution, output parsing, and integrity verification.
"""

from .system_detect import SystemDetector, PartitionInfo
from .validator import SystemValidator, ValidationResult
from .ssh_client import SSHClient
from .progress_parser import ProgressParser, TransferProgress
from .rsync_runner import RsyncRunner, RsyncExecutionResult
from .verifier import Verifier, VerificationReport

__all__ = [
    "SystemDetector",
    "PartitionInfo",
    "SystemValidator",
    "ValidationResult",
    "SSHClient",
    "ProgressParser",
    "TransferProgress",
    "RsyncRunner",
    "RsyncExecutionResult",
    "Verifier",
    "VerificationReport",
]
"""
Common Package.

Contains shared constants, domain exceptions, metadata models,
and unified logging utilities for both Client and Desktop layers.
"""

from .constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_SSH_PORT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_SAFETY_MARGIN,
    SUPPORTED_FILESYSTEMS,
    PARTIAL_SUFFIX,
    LOCK_FILENAME,
    METADATA_FILENAME,
    BackupStatus,
)
from .exceptions import (
    BackupSystemError,
    NetworkError,
    AuthenticationError,
    DestinationDiskFullError,
    SourcePartitionError,
    RsyncExecutionError,
    VerificationError,
    LockAcquisitionError,
)
from .metadata_model import BackupMetadata
from .logger import setup_logger

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "DEFAULT_SSH_PORT",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_SAFETY_MARGIN",
    "SUPPORTED_FILESYSTEMS",
    "PARTIAL_SUFFIX",
    "LOCK_FILENAME",
    "METADATA_FILENAME",
    "BackupStatus",
    "BackupSystemError",
    "NetworkError",
    "AuthenticationError",
    "DestinationDiskFullError",
    "SourcePartitionError",
    "RsyncExecutionError",
    "VerificationError",
    "LockAcquisitionError",
    "BackupMetadata",
    "setup_logger",
]
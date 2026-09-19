"""
SQLite Catalog Manager.
Tracks backup metadata, statuses, timestamps, and audit results.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite storage catalog transactions."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initializes tables using schemas/database.sql."""
        schema_file = Path(__file__).resolve().parent.parent / "schemas" / "database.sql"
        if not schema_file.exists():
            raise FileNotFoundError(f"Database schema file not found at: {schema_file}")

        with self._get_connection() as conn:
            with open(schema_file, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.commit()

    def record_backup_start(
        self,
        backup_id: str,
        client_hostname: str,
        source_partition: str,
        source_mountpoint: Optional[str],
        filesystem_type: str,
        storage_path: str,
    ) -> None:
        """Creates a record when an rsync session starts."""
        now_str = datetime.now().isoformat()
        query = """
            INSERT INTO backups (
                backup_id, client_hostname, source_partition, source_mountpoint,
                filesystem_type, status, storage_path, started_at
            ) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(
                query,
                (
                    backup_id,
                    client_hostname,
                    source_partition,
                    source_mountpoint,
                    filesystem_type,
                    storage_path,
                    now_str,
                ),
            )
            conn.commit()

    def record_backup_completion(
        self,
        backup_id: str,
        bytes_transferred: int,
        status: str = "COMPLETED",
        notes: Optional[str] = None,
    ) -> None:
        """Updates record upon successful transfer or caught failure."""
        now_str = datetime.now().isoformat()
        query = """
            UPDATE backups
            SET bytes_transferred = ?, status = ?, completed_at = ?, notes = ?
            WHERE backup_id = ?
        """
        with self._get_connection() as conn:
            conn.execute(query, (bytes_transferred, status, now_str, notes, backup_id))
            conn.commit()

    def record_audit(
        self,
        backup_id: str,
        total_files: int,
        total_bytes: int,
        sample_checked: int,
        is_valid: bool,
        summary: str,
    ) -> None:
        """Inserts post-transfer integrity audit findings."""
        now_str = datetime.now().isoformat()
        query = """
            INSERT INTO integrity_audits (
                backup_id, audit_timestamp, total_files, total_bytes,
                sample_files_checked, is_valid, audit_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(
                query,
                (
                    backup_id,
                    now_str,
                    total_files,
                    total_bytes,
                    sample_checked,
                    1 if is_valid else 0,
                    summary,
                ),
            )
            conn.commit()

    def mark_as_pruned(self, backup_id: str) -> None:
        """Updates status of a purged backup."""
        with self._get_connection() as conn:
            conn.execute("UPDATE backups SET status = 'PRUNED' WHERE backup_id = ?", (backup_id,))
            conn.commit()

    def get_backups(
        self,
        client_hostname: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Queries recorded backups, optionally filtered by host."""
        query = "SELECT * FROM backups"
        params: List[Any] = []

        if client_hostname:
            query += " WHERE client_hostname = ?"
            params.append(client_hostname)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_backup_by_id(self, backup_id: str) -> Optional[Dict[str, Any]]:
        """Fetches complete record of a specific backup."""
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM backups WHERE backup_id = ?", (backup_id,))
            row = cur.fetchone()
            return dict(row) if row else None
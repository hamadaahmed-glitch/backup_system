"""
Backup Retention and Pruning Engine.
Applies retention policies (by count or by age) to remove obsolete 
backups safely and maintain disk quotas.
"""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from .db_manager import DatabaseManager
from .storage_manager import StorageManager

logger = logging.getLogger(__name__)


class RetentionManager:
    """Calculates and prunes expired or excess backups."""

    def __init__(self, storage_manager: StorageManager, db_manager: DatabaseManager) -> None:
        self.storage = storage_manager
        self.db = db_manager

    def prune_by_count(self, client_hostname: str, keep_last: int = 5) -> List[str]:
        """
        Retains the newest N completed backups for a specific client.
        Purges older backups from disk and marks them as PRUNED in the database.
        """
        if keep_last < 1:
            raise ValueError("keep_last must be at least 1")

        backups = self.db.get_backups(client_hostname=client_hostname, limit=500)
        # Filter down to only completed runs
        completed_backups = [b for b in backups if b["status"] == "COMPLETED"]

        if len(completed_backups) <= keep_last:
            logger.info(
                "Client '%s' has %d backups (<= %d). No pruning necessary.",
                client_hostname,
                len(completed_backups),
                keep_last,
            )
            return []

        # Sort descending by ID, then slice off anything past keep_last
        to_prune = completed_backups[keep_last:]
        pruned_ids: List[str] = []

        for b in to_prune:
            backup_id = b["backup_id"]
            path = Path(b["storage_path"])
            logger.info("Pruning excess backup: %s at %s", backup_id, path)

            if path.exists() and path.is_dir():
                try:
                    shutil.rmtree(path)
                    logger.info("Successfully removed directory %s", path)
                except Exception as e:
                    logger.error("Failed to delete directory %s: %s", path, e)
                    continue

            self.db.mark_as_pruned(backup_id)
            pruned_ids.append(backup_id)

        return pruned_ids

    def prune_by_age(self, client_hostname: str, max_days: int = 30) -> List[str]:
        """
        Prunes backups older than max_days, ensuring at least 1 backup is always preserved.
        """
        backups = self.db.get_backups(client_hostname=client_hostname, limit=500)
        completed_backups = [b for b in backups if b["status"] == "COMPLETED"]

        if len(completed_backups) <= 1:
            logger.info("Only 1 or zero backups remain for %s. Skipping age-based pruning.", client_hostname)
            return []

        cutoff_date = datetime.now() - timedelta(days=max_days)
        pruned_ids: List[str] = []

        # Exclude the very newest backup to avoid deleting the only available copy
        candidates = completed_backups[1:]

        for b in candidates:
            started_at = datetime.fromisoformat(b["started_at"])
            if started_at < cutoff_date:
                backup_id = b["backup_id"]
                path = Path(b["storage_path"])
                logger.info("Pruning expired backup (%s days old): %s", max_days, backup_id)

                if path.exists() and path.is_dir():
                    try:
                        shutil.rmtree(path)
                    except Exception as e:
                        logger.error("Failed to delete expired backup at %s: %s", path, e)
                        continue

                self.db.mark_as_pruned(backup_id)
                pruned_ids.append(backup_id)

        return pruned_ids
#!/usr/bin/env python3
"""
Desktop Backup Manager CLI.
Entry point for managing storage, querying job histories,
auditing integrity, and executing maintenance pruning routines.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path to support execution as a standalone script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop.core.db_manager import DatabaseManager
from desktop.core.integrity_check import IntegrityChecker
from desktop.core.retention import RetentionManager
from desktop.core.storage_manager import StorageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("desktop.manager")

DEFAULT_STORAGE_ROOT = PROJECT_ROOT / "storage"
DEFAULT_DB_PATH = PROJECT_ROOT / "storage" / "backup_catalog.db"


def cmd_init(args: argparse.Namespace) -> None:
    """Initializes local storage folders and SQLite database catalog."""
    storage_root = Path(args.storage_root).resolve()
    db_path = Path(args.db_path).resolve()

    StorageManager(storage_root)
    DatabaseManager(db_path)
    print(f"Initialized storage repository at: {storage_root}")
    print(f"Initialized SQLite database at:      {db_path}")


def cmd_history(args: argparse.Namespace) -> None:
    """Lists recorded backup sessions."""
    db = DatabaseManager(Path(args.db_path))
    records = db.get_backups(client_hostname=args.client, limit=args.limit)

    if not records:
        print("No backup records found.")
        return

    fmt = "{:<28} {:<16} {:<12} {:<12} {:<20}"
    print("-" * 92)
    print(fmt.format("Backup ID", "Client", "Status", "Size (GB)", "Started At"))
    print("-" * 92)

    for r in records:
        size_gb = f"{r['bytes_transferred'] / (1024**3):.2f}"
        print(
            fmt.format(
                r["backup_id"][:27],
                r["client_hostname"][:15],
                r["status"],
                size_gb,
                r["started_at"][:19],
            )
        )
    print("-" * 92)


def cmd_verify(args: argparse.Namespace) -> None:
    """Runs a server-side data integrity audit on a specific backup directory."""
    db = DatabaseManager(Path(args.db_path))
    checker = IntegrityChecker()

    target_path = Path(args.backup_dir).resolve()
    backup_id = target_path.name

    print(f"Running integrity audit on: {target_path} ...")
    report = checker.audit_backup_directory(backup_id, target_path)

    print(f"Audit Status : {'PASSED' if report.is_valid else 'FAILED'}")
    print(f"Total Files  : {report.total_files}")
    print(f"Total Size   : {report.total_bytes / (1024**3):.2f} GB")
    print(f"Summary      : {report.summary}")

    # Log audit into DB if backup exists
    record = db.get_backup_by_id(backup_id)
    if record:
        db.record_audit(
            backup_id=backup_id,
            total_files=report.total_files,
            total_bytes=report.total_bytes,
            sample_checked=report.sample_files_checked,
            is_valid=report.is_valid,
            summary=report.summary,
        )
        print("Audit results logged to database catalog.")


def cmd_prune(args: argparse.Namespace) -> None:
    """Executes retention policies to purge old backups."""
    storage = StorageManager(Path(args.storage_root))
    db = DatabaseManager(Path(args.db_path))
    retention = RetentionManager(storage, db)

    if args.keep_last:
        print(f"Pruning backups for '{args.client}', keeping last {args.keep_last}...")
        pruned = retention.prune_by_count(args.client, keep_last=args.keep_last)
        print(f"Pruned {len(pruned)} backup(s): {pruned}")

    elif args.max_days:
        print(f"Pruning backups for '{args.client}' older than {args.max_days} days...")
        pruned = retention.prune_by_age(args.client, max_days=args.max_days)
        print(f"Pruned {len(pruned)} backup(s): {pruned}")


def cmd_finalize(args: argparse.Namespace) -> None:
    """
    Finalizes an incoming transfer:
    Promotes .partial directory to complete, writes metadata, and logs completion in SQLite.
    Can be invoked remotely by client automation.
    """
    storage = StorageManager(Path(args.storage_root))
    db = DatabaseManager(Path(args.db_path))

    staging_dir = Path(args.staging_dir).resolve()
    final_dir = storage.promote_to_complete(staging_dir)

    if args.metadata_json:
        try:
            meta = json.loads(args.metadata_json)
            storage.write_metadata(final_dir, meta)
        except Exception as e:
            logger.warning("Failed to decode and write metadata: %s", e)

    db.record_backup_completion(
        backup_id=final_dir.name,
        bytes_transferred=args.bytes_transferred,
        status="COMPLETED",
    )
    print(f"SUCCESS: Backup promoted to: {final_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Desktop Backup Storage and Catalog Manager",
    )
    parser.add_argument(
        "--storage-root",
        default=str(DEFAULT_STORAGE_ROOT),
        help="Directory where client backups are stored",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite catalog database file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Init
    p_init = subparsers.add_parser("init", help="Initialize storage paths and catalog database")
    p_init.set_defaults(func=cmd_init)

    # History
    p_hist = subparsers.add_parser("history", help="List recorded backups")
    p_hist.add_argument("--client", help="Filter by client hostname")
    p_hist.add_argument("--limit", type=int, default=30, help="Max entries to return")
    p_hist.set_defaults(func=cmd_history)

    # Verify
    p_ver = subparsers.add_parser("verify", help="Audit integrity of a backup folder")
    p_ver.add_argument("backup_dir", help="Path to backup directory")
    p_ver.set_defaults(func=cmd_verify)

    # Prune
    p_prune = subparsers.add_parser("prune", help="Enforce retention policy")
    p_prune.add_argument("--client", required=True, help="Target client hostname")
    group = p_prune.add_mutually_exclusive_group(required=True)
    group.add_argument("--keep-last", type=int, help="Retain last N backups")
    group.add_argument("--max-days", type=int, help="Purge backups older than N days")
    p_prune.set_defaults(func=cmd_prune)

    # Finalize
    p_fin = subparsers.add_parser("finalize", help="Promote .partial backup to complete")
    p_fin.add_argument("staging_dir", help="Path to staging .partial directory")
    p_fin.add_argument("--bytes-transferred", type=int, default=0)
    p_fin.add_argument("--metadata-json", help="JSON metadata string to store")
    p_fin.set_defaults(func=cmd_finalize)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
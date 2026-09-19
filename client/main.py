#!/usr/bin/env python3
"""
Laptop Backup Client CLI.

Primary entry point for backing up an Ubuntu partition to a remote Desktop
over SSH + rsync. Handles configuration loading, pre-flight safety checks,
live progress parsing, process lifecycle, and post-transfer verification.
"""

import argparse
import getpass
import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root is available in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.core.rsync_runner import RsyncRunner
from client.core.ssh_client import SSHClient
from client.core.system_detect import SystemDetector
from client.core.validator import SystemValidator
from client.core.verifier import Verifier
from client.ui.cli_view import CLIView
from client.ui.tui_dashboard import TUIDashboard
from common.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_RSYNC_EXCLUDES,
    DEFAULT_SAFETY_MARGIN,
    DEFAULT_SSH_PORT,
    METADATA_FILENAME,
    PARTIAL_SUFFIX,
    BackupStatus,
)
from common.logger import setup_logger
from common.metadata_model import BackupMetadata

# Initialize file and console logging
LOG_DIR = PROJECT_ROOT / "logs" / "client"
logger = setup_logger("client", log_dir=LOG_DIR, log_file="client_backup.log")


def load_config(config_path: Optional[Path]) -> Dict[str, Any]:
    """Loads configuration defaults from JSON if available."""
    default_config_file = PROJECT_ROOT / "config" / "client_config.json"
    target_path = config_path or default_config_file

    if target_path.exists() and target_path.is_file():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not parse config at %s: %s", target_path, e)

    return {}


def parse_arguments(config_defaults: Dict[str, Any]) -> argparse.Namespace:
    """Configures and parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} v{APP_VERSION} - Laptop Partition Backup Client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-s", "--source",
        default=config_defaults.get("default_source"),
        help="Source partition device (e.g. /dev/nvme0n1p3) or mountpoint (e.g. /home)",
    )
    parser.add_argument(
        "-H", "--desktop-host",
        default=config_defaults.get("desktop_host"),
        help="Desktop IP address or hostname",
    )
    parser.add_argument(
        "-u", "--desktop-user",
        default=config_defaults.get("desktop_user", "backup-user"),
        help="SSH username on the Desktop target",
    )
    parser.add_argument(
        "-d", "--desktop-path",
        default=config_defaults.get("destination_root", "/srv/backups"),
        help="Root storage directory on the Desktop",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=config_defaults.get("ssh_port", DEFAULT_SSH_PORT),
        help="Desktop SSH port",
    )
    parser.add_argument(
        "-i", "--key",
        default=config_defaults.get("ssh_key", "~/.ssh/id_ed25519_backup"),
        help="Path to SSH private key identity file",
    )
    parser.add_argument(
        "-l", "--list-partitions",
        action="store_true",
        help="Scan and display all local storage partitions, then exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a trial run with no changes made to remote storage",
    )
    parser.add_argument(
        "-z", "--compress",
        action="store_true",
        default=config_defaults.get("compress", False),
        help="Enable rsync stream compression (useful for slow Wi-Fi, not needed on Gigabit)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch interactive terminal dashboard using Rich (if installed)",
    )
    parser.add_argument(
        "--safety-margin",
        type=float,
        default=config_defaults.get("safety_margin", DEFAULT_SAFETY_MARGIN),
        help="Disk safety buffer ratio on destination (0.10 = 10%)",
    )

    return parser.parse_args()


def main() -> None:
    # 1. Load configuration and CLI arguments
    config = load_config(None)
    args = parse_arguments(config)
    ui = CLIView()

    # 2. Handle block device inspection mode
    detector = SystemDetector()
    if args.list_partitions:
        ui.print_banner()
        partitions = detector.list_block_devices()
        ui.render_partitions_table(partitions)
        sys.exit(0)

    # 3. Validate required arguments
    if not args.source:
        ui.print_banner()
        print("Error: Source partition or mountpoint required. Use -s/--source or specify in config.")
        print("Tip: Run with -l or --list-partitions to view available devices.\n")
        sys.exit(1)

    if not args.desktop_host:
        ui.print_banner()
        print("Error: Desktop host IP/hostname required. Use -H/--desktop-host or specify in config.\n")
        sys.exit(1)

    # 4. Resolve source partition details
    ui.print_banner()
    logger.info("Detecting source storage configuration for '%s'...", args.source)
    partition = detector.get_partition_by_path_or_mount(args.source)

    if not partition:
        logger.error("Could not resolve source identifier: %s", args.source)
        print(f"Error: Target '{args.source}' is not a recognized partition or mountpoint.")
        sys.exit(1)

    # 5. Initialize network & SSH layer
    key_path = os.path.expanduser(args.key) if args.key else None
    ssh = SSHClient(
        host=args.desktop_host,
        user=args.desktop_user,
        port=args.port,
        identity_file=key_path,
    )

    # 6. Execute pre-flight validation checklist
    logger.info("Running pre-flight checks against Desktop [%s:%d]...", args.desktop_host, args.port)
    validator = SystemValidator(ssh)
    validation_res = validator.validate_pre_flight(
        partition=partition,
        destination_path=args.desktop_path,
        safety_margin_ratio=args.safety_margin,
    )

    ui.render_validation_result(validation_res)

    if not validation_res.is_valid:
        logger.error("Pre-flight safety validation failed. Aborting backup.")
        sys.exit(1)

    # 7. Construct target hierarchy and backup identifiers
    hostname = socket.gethostname()
    username = getpass.getuser()
    timestamp_str = time.strftime("%Y-%m-%d-%H%M%S")
    backup_id = f"{hostname}-{timestamp_str}"

    remote_client_dir = f"{args.desktop_path.rstrip('/')}/{hostname}"
    remote_staging_dir = f"{remote_client_dir}/{backup_id}{PARTIAL_SUFFIX}"
    remote_final_dir = f"{remote_client_dir}/{backup_id}"

    # Initialize Metadata tracking
    metadata = BackupMetadata.create_new(
        client_hostname=hostname,
        client_username=username,
        source_partition=partition.device_path,
        source_mountpoint=partition.mountpoint or args.source,
        filesystem_type=partition.fstype,
        filesystem_uuid=partition.uuid,
        storage_path=remote_final_dir,
    )

    # 8. Setup user interface
    use_tui = args.tui
    tui: Optional[TUIDashboard] = None

    if use_tui:
        tui = TUIDashboard(fallback_cli=ui)
        tui.start_session(
            partition=partition,
            destination_target=f"{args.desktop_user}@{args.desktop_host}:{remote_staging_dir}",
            total_source_bytes=partition.used_bytes,
        )

    def on_progress_update(progress):
        if tui and tui.is_rich_available():
            tui.update_progress(progress)
        else:
            ui.render_progress(progress, partition.used_bytes)

    # 9. Configure and execute rsync operation
    runner = RsyncRunner(
        source_dir=partition.mountpoint,
        dest_user=args.desktop_user,
        dest_host=args.desktop_host,
        dest_path=remote_staging_dir,
        ssh_port=args.port,
        identity_file=key_path,
        compress=args.compress,
        dry_run=args.dry_run,
        exclude_patterns=DEFAULT_RSYNC_EXCLUDES,
    )

    start_time = time.time()
    logger.info("Executing rsync transfer: %s -> %s", partition.mountpoint, remote_staging_dir)

    exec_result = runner.execute(progress_callback=on_progress_update)
    duration = time.time() - start_time

    # Close TUI safely before printing final summaries
    if tui:
        tui.close()

    # 10. Handle interruptions
    if exec_result.was_interrupted:
        logger.warning("Transfer interrupted by user or signal. State preserved in .partial/")
        metadata.mark_failed("Interrupted by user / signal.")
        ui.render_summary(
            exec_result=exec_result,
            report=None,
            duration_seconds=duration,
        )
        sys.exit(130)

    # 11. Run post-transfer integrity verification
    logger.info("Conducting post-transfer verification checks...")
    verifier = Verifier(ssh)
    report = verifier.quick_post_transfer_check(
        source_dir=partition.mountpoint,
        remote_dest_dir=remote_staging_dir,
        rsync_exit_code=exec_result.exit_code,
    )

    # 12. Finalization & Promotion on Success
    if report.is_success and not args.dry_run:
        logger.info("Verification passed. Promoting staging directory to complete...")
        metadata.mark_completed(
            bytes_transferred=exec_result.total_bytes_transferred,
            duration_seconds=duration,
            integrity_verified=True,
            notes=f"Rsync completed cleanly (Code {exec_result.exit_code}).",
        )

        # Atomic remote rename: .partial -> final
        rename_cmd = f"mv {remote_staging_dir} {remote_final_dir}"
        code, _, err = ssh.run_command(rename_cmd)
        if code != 0:
            logger.error("Failed to atomically promote remote directory: %s", err.strip())
        else:
            logger.info("Directory promoted successfully to: %s", remote_final_dir)

            # Write metadata directly into remote archive
            meta_json = json.dumps(metadata.to_dict(), indent=2)
            meta_remote_path = f"{remote_final_dir}/{METADATA_FILENAME}"
            write_meta_cmd = f"cat << 'EOF' > {meta_remote_path}\n{meta_json}\nEOF"
            ssh.run_command(write_meta_cmd)

            # Record in remote history database if desktop manager is deployed
            remote_finalize_cmd = (
                f"python3 -m desktop.manager finalize {remote_staging_dir} "
                f"--bytes-transferred {exec_result.total_bytes_transferred} "
                f"--storage-root {args.desktop_path}"
            )
            ssh.run_command(remote_finalize_cmd)

    elif not report.is_success:
        logger.error("Verification audit failed: %s", report.status_summary)
        metadata.mark_failed(report.status_summary)

    # 13. Render final reporting
    ui.render_summary(
        exec_result=exec_result,
        report=report,
        duration_seconds=duration,
    )

    sys.exit(0 if report.is_success else 1)


if __name__ == "__main__":
    main()
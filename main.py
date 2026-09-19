#!/usr/bin/env python3
"""
==============================================================================
               LINUX PARTITION BACKUP SYSTEM - UNIFIED CONTROLLER
==============================================================================
Universal entry point for both SENDER (Laptop) and RECEIVER (Desktop).
Supports an interactive terminal wizard or direct CLI automation.
"""

import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is present in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Internal System Imports
from client.core.rsync_runner import RsyncRunner
from client.core.ssh_client import SSHClient
from client.core.system_detect import PartitionInfo, SystemDetector
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
from desktop.core.db_manager import DatabaseManager
from desktop.core.integrity_check import IntegrityChecker
from desktop.core.retention import RetentionManager
from desktop.core.storage_manager import StorageManager

# Unified Logger Setup
logger = setup_logger("unified_main", log_dir=PROJECT_ROOT / "logs", log_file="system.log")


# ============================================================================
# ANSI Color & Visual Formatting Helpers
# ============================================================================
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    @classmethod
    def header(cls, text: str) -> None:
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        print(f"\n{cls.CYAN}{'=' * cols}{cls.RESET}")
        print(f"{cls.BOLD}{cls.WHITE}  {text}{cls.RESET}")
        print(f"{cls.CYAN}{'=' * cols}{cls.RESET}")

    @classmethod
    def section(cls, text: str) -> None:
        print(f"\n{cls.BOLD}{cls.MAGENTA}--- {text} ---{cls.RESET}")

    @classmethod
    def prompt(cls, message: str, default: Optional[str] = None) -> str:
        if default:
            p = f"{cls.BOLD}{cls.CYAN}{message}{cls.RESET} [{cls.GREEN}{default}{cls.RESET}]: "
        else:
            p = f"{cls.BOLD}{cls.CYAN}{message}{cls.RESET}: "
        val = input(p).strip()
        return val if val else (default or "")


# ============================================================================
# Configuration Loader
# ============================================================================
def load_config_defaults() -> Dict[str, Any]:
    """Loads default configurations for both client and desktop."""
    cfg = {
        "desktop_host": "192.168.1.50",
        "desktop_user": "backup-user",
        "storage_root": "/srv/backups",
        "ssh_port": 22,
        "ssh_key": str(Path.home() / ".ssh" / "id_ed25519_backup"),
        "default_source": "/home",
        "safety_margin": 0.10,
    }

    client_cfg_file = PROJECT_ROOT / "config" / "client_config.json"
    if client_cfg_file.exists():
        try:
            with open(client_cfg_file, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            logger.warning("Failed to load client_config.json: %s", e)

    desktop_cfg_file = PROJECT_ROOT / "config" / "desktop_config.json"
    if desktop_cfg_file.exists():
        try:
            with open(desktop_cfg_file, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            logger.warning("Failed to load desktop_config.json: %s", e)

    return cfg


# ============================================================================
# MODULE 1: SENDER (LAPTOP) WORKFLOWS
# ============================================================================
def run_sender_workflow(
    source_override: Optional[str] = None,
    host_override: Optional[str] = None,
    user_override: Optional[str] = None,
    dest_path_override: Optional[str] = None,
    port_override: Optional[int] = None,
    key_override: Optional[str] = None,
    use_tui: bool = False,
    dry_run: bool = False,
    compress: bool = False,
) -> None:
    """Executes the full sending procedure from Laptop to Desktop."""
    Style.header("ROLE: SENDER (LAPTOP) - SYNCHRONIZATION ENGINE")
    cfg = load_config_defaults()
    ui = CLIView()
    detector = SystemDetector()
    temp_mounted = False
    mounted_device_to_clean = None

    # 1. Source Partition Selection
    source = source_override
    if not source:
        Style.section("Step 1: Select Local Source Partition")
        # List ONLY real storage partitions (filters out loop/snap devices)
        partitions = detector.list_block_devices(include_loop=False)
        ui.render_partitions_table(partitions)

        # Filter to actual partition targets
        selectable_partitions = [
            p for p in partitions if not p.name.startswith("loop") and p.fstype != "unknown"
        ]

        if not selectable_partitions:
            print(f"{Style.RED}Error: No physical storage partitions found.{Style.RESET}")
            return

        print("\nAvailable Storage Partitions:")
        for idx, p in enumerate(selectable_partitions, 1):
            status = f"{Style.GREEN}{p.mountpoint}{Style.RESET}" if p.is_mounted else f"{Style.YELLOW}[Unmounted]{Style.RESET}"
            size_gb = p.total_bytes / (1024**3)
            print(f"  [{Style.GREEN}{idx}{Style.RESET}] {p.device_path:<16} ({p.fstype:<5}) - Total: {size_gb:6.2f} GB - {status}")

        choice = Style.prompt(
            f"Select partition number (1-{len(selectable_partitions)}) or enter path",
            default="1",
        )

        if choice.isdigit() and 1 <= int(choice) <= len(selectable_partitions):
            selected_partition = selectable_partitions[int(choice) - 1]
            source = selected_partition.device_path
        else:
            source = choice

    # Resolve partition details
    partition = detector.get_partition_by_path_or_mount(source)
    if not partition:
        print(f"{Style.RED}Error: Cannot resolve partition '{source}'.{Style.RESET}")
        return

    # Auto-Mount if the selected partition is unmounted (e.g. /dev/nvme0n1p2)
    if not partition.is_mounted:
        print(f"\n{Style.YELLOW}Partition {partition.device_path} is currently UNMOUNTED.{Style.RESET}")
        print(f"Mounting {partition.device_path} temporarily to read its files...")
        ok, mount_res = detector.mount_partition(partition.device_path)
        if not ok:
            print(f"{Style.RED}Failed to mount {partition.device_path}: {mount_res}{Style.RESET}")
            print(f"Tip: Try mounting it manually via: sudo mount {partition.device_path} /mnt")
            return
        
        print(f"{Style.GREEN}Successfully mounted at: {mount_res}{Style.RESET}")
        temp_mounted = True
        mounted_device_to_clean = partition.device_path
        # Refresh partition stats with the new mountpoint
        partition = detector.get_partition_by_path_or_mount(partition.device_path)

    try:
        # 2. Remote Destination Configuration
        Style.section("Step 2: Destination Settings")
        host = host_override or Style.prompt("Desktop IP or Hostname", cfg["desktop_host"])
        user = user_override or Style.prompt("Desktop SSH Username", cfg["desktop_user"])
        port = port_override or int(Style.prompt("SSH Port", str(cfg["ssh_port"])))
        dest_path = dest_path_override or Style.prompt("Remote Storage Root Directory", cfg["storage_root"])
        key_path = key_override or Style.prompt("SSH Private Key Path", cfg["ssh_key"])
        key_path = os.path.expanduser(key_path)

        # 3. Connection and Pre-Flight Validation
        Style.section("Step 3: Pre-Flight Safety Validation")
        ssh = SSHClient(host=host, user=user, port=port, identity_file=key_path)
        validator = SystemValidator(ssh)

        validation_res = validator.validate_pre_flight(
            partition=partition,
            destination_path=dest_path,
            safety_margin_ratio=cfg["safety_margin"],
        )
        ui.render_validation_result(validation_res)

        if not validation_res.is_valid:
            print(f"{Style.RED}Aborting transfer due to validation failures.{Style.RESET}")
            return

        # Confirm Execution
        confirm = Style.prompt("Begin data synchronization now? (y/n)", "y").lower()
        if confirm not in ("y", "yes"):
            print("Operation canceled by user.")
            return

        # 4. Target Directory Setup
        hostname = socket.gethostname()
        username = getpass.getuser()
        timestamp_str = time.strftime("%Y-%m-%d-%H%M%S")
        backup_id = f"{hostname}-{timestamp_str}"

        remote_client_dir = f"{dest_path.rstrip('/')}/{hostname}"
        remote_staging_dir = f"{remote_client_dir}/{backup_id}{PARTIAL_SUFFIX}"
        remote_final_dir = f"{remote_client_dir}/{backup_id}"

        metadata = BackupMetadata.create_new(
            client_hostname=hostname,
            client_username=username,
            source_partition=partition.device_path,
            source_mountpoint=partition.mountpoint or source,
            filesystem_type=partition.fstype,
            filesystem_uuid=partition.uuid,
            storage_path=remote_final_dir,
        )

        # 5. Launch rsync
        tui: Optional[TUIDashboard] = None
        if use_tui:
            tui = TUIDashboard(fallback_cli=ui)
            tui.start_session(
                partition=partition,
                destination_target=f"{user}@{host}:{remote_staging_dir}",
                total_source_bytes=partition.used_bytes,
            )

        def on_progress(p):
            if tui and tui.is_rich_available():
                tui.update_progress(p)
            else:
                ui.render_progress(p, partition.used_bytes)

        is_ntfs = partition.fstype.lower() == "ntfs"

        runner = RsyncRunner(
            source_dir=partition.mountpoint,
            dest_user=user,
            dest_host=host,
            dest_path=remote_staging_dir,
            ssh_port=port,
            identity_file=key_path,
            compress=compress,
            dry_run=dry_run,
            is_ntfs=is_ntfs,
            exclude_patterns=DEFAULT_RSYNC_EXCLUDES,
        )

        Style.section("Step 4: Transfer In Progress")
        start_time = time.time()
        result = runner.execute(progress_callback=on_progress)
        duration = time.time() - start_time

        if tui:
            tui.close()

        # 6. Interruption Handling
        if result.was_interrupted:
            ui.render_summary(result, None, duration)
            print(f"\n{Style.YELLOW}Transfer state saved in '{remote_staging_dir}'. Re-run to resume.{Style.RESET}")
            return

        # 7. Verification & Promotion
        Style.section("Step 5: Post-Transfer Verification")
        verifier = Verifier(ssh)
        report = verifier.quick_post_transfer_check(
            source_dir=partition.mountpoint,
            remote_dest_dir=remote_staging_dir,
            rsync_exit_code=result.exit_code,
        )

        if report.is_success and not dry_run:
            metadata.mark_completed(
                bytes_transferred=result.total_bytes_transferred,
                duration_seconds=duration,
                integrity_verified=True,
            )
            # Promote .partial -> final
            promote_cmd = f"mv {remote_staging_dir} {remote_final_dir}"
            ssh.run_command(promote_cmd)

            meta_json = json.dumps(metadata.to_dict(), indent=2)
            meta_remote_path = f"{remote_final_dir}/{METADATA_FILENAME}"
            ssh.run_command(f"cat << 'EOF' > {meta_remote_path}\n{meta_json}\nEOF")

        ui.render_summary(result, report, duration)

    finally:
        # Clean up temporary mount if we mounted it
        if temp_mounted and mounted_device_to_clean:
            print(f"\nCleaning up temporary mount for {mounted_device_to_clean}...")
            detector.unmount_partition(mounted_device_to_clean)

# ============================================================================
# MODULE 2: RECEIVER (DESKTOP) WORKFLOWS
# ============================================================================
def get_valid_storage_root(default_path: str) -> Path:
    """
    Checks if the storage path is writable.
    If not, falls back to a user-writable directory (~/Backups or ./storage).
    """
    target = Path(default_path).expanduser().resolve()
    try:
        target.mkdir(parents=True, exist_ok=True)
        test_file = target / ".perm_check"
        test_file.touch()
        test_file.unlink()
        return target
    except (PermissionError, OSError):
        # Fallback to project root storage or home directory
        fallback = PROJECT_ROOT / "storage"
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"\n{Style.YELLOW}[Notice] '{default_path}' is not writable without root.{Style.RESET}")
        print(f"{Style.GREEN}Auto-selected accessible storage path: {fallback}{Style.RESET}")
        print(f"To use '{default_path}', run: sudo mkdir -p {default_path} && sudo chown -R $USER:$USER {default_path}\n")
        return fallback


def run_receiver_menu() -> None:
    """Interactive management dashboard for the Receiver/Desktop machine."""
    cfg = load_config_defaults()
    
    # Auto-resolves permissions gracefully
    storage_root = get_valid_storage_root(cfg["storage_root"])
    db_path = storage_root / "backup_catalog.db"

    storage = StorageManager(storage_root)
    db = DatabaseManager(db_path)
    integrity = IntegrityChecker()
    retention = RetentionManager(storage, db)

    while True:
        Style.header("ROLE: RECEIVER (DESKTOP) - REPOSITORY & CATALOG MANAGER")
        print(f" Storage Path : {Style.GREEN}{storage_root}{Style.RESET}")
        print(f" Catalog DB   : {Style.GREEN}{db_path}{Style.RESET}")
        print("\nOperations:")
        print(f"  [{Style.GREEN}1{Style.RESET}] View Backup History & Catalog Records")
        print(f"  [{Style.GREEN}2{Style.RESET}] Run Storage Integrity Audit on a Backup")
        print(f"  [{Style.GREEN}3{Style.RESET}] Prune Old Backups (Retention Rules)")
        print(f"  [{Style.GREEN}4{Style.RESET}] View Disk Space & Storage Status")
        print(f"  [{Style.GREEN}5{Style.RESET}] Re-initialize Database & Directories")
        print(f"  [{Style.YELLOW}0{Style.RESET}] Return to Main Portal")

        choice = Style.prompt("\nSelect option", "1")

        if choice == "1":
            client = Style.prompt("Filter by client hostname (Leave blank for all)", "")
            records = db.get_backups(client_hostname=client if client else None)
            if not records:
                print(f"\n{Style.YELLOW}No backup records found in catalog.{Style.RESET}")
            else:
                fmt = "{:<30} {:<16} {:<12} {:<12} {:<20}"
                print("\n" + "-" * 94)
                print(fmt.format("Backup ID", "Client", "Status", "Size (GB)", "Started At"))
                print("-" * 94)
                for r in records:
                    size_gb = f"{r['bytes_transferred'] / (1024**3):.2f}"
                    status_col = Style.GREEN if r["status"] == "COMPLETED" else Style.RED
                    print(
                        fmt.format(
                            r["backup_id"][:29],
                            r["client_hostname"][:15],
                            f"{status_col}{r['status']}{Style.RESET}",
                            size_gb,
                            r["started_at"][:19],
                        )
                    )
                print("-" * 94)
            input("\nPress Enter to return...")

        elif choice == "2":
            records = db.get_backups(limit=20)
            completed = [r for r in records if r["status"] == "COMPLETED"]
            if not completed:
                print(f"\n{Style.YELLOW}No completed backups available to audit.{Style.RESET}")
                input("\nPress Enter...")
                continue

            print("\nSelect a backup to audit:")
            for idx, r in enumerate(completed, 1):
                print(f"  [{idx}] {r['backup_id']} ({r['client_hostname']})")

            sel = Style.prompt(f"Select (1-{len(completed)})", "1")
            if sel.isdigit() and 1 <= int(sel) <= len(completed):
                target = completed[int(sel) - 1]
                target_path = Path(target["storage_path"])
                print(f"\nAuditing: {target_path} ...")
                report = integrity.audit_backup_directory(target["backup_id"], target_path)

                print(f" Status      : {Style.GREEN if report.is_valid else Style.RED}{'PASSED' if report.is_valid else 'FAILED'}{Style.RESET}")
                print(f" Total Files : {report.total_files}")
                print(f" Total Size  : {report.total_bytes / (1024**3):.2f} GB")
                print(f" Summary     : {report.summary}")
            input("\nPress Enter to return...")

        elif choice == "3":
            client = Style.prompt("Client hostname to prune")
            if not client:
                continue
            keep_n = Style.prompt("Number of newest backups to KEEP", "3")
            if keep_n.isdigit():
                pruned = retention.prune_by_count(client, keep_last=int(keep_n))
                print(f"\n{Style.GREEN}Pruned {len(pruned)} backup(s): {pruned}{Style.RESET}")
            input("\nPress Enter to return...")

        elif choice == "4":
            print(f"\n{Style.BOLD}Storage Disk Space:{Style.RESET}")
            subprocess.run(["df", "-h", str(storage_root)])
            input("\nPress Enter to return...")

        elif choice == "5":
            StorageManager(storage_root)
            DatabaseManager(db_path)
            print(f"\n{Style.GREEN}Storage repository and SQLite database initialized successfully!{Style.RESET}")
            input("\nPress Enter to return...")

        elif choice in ("0", "exit", "q"):
            break

# ============================================================================
# MODULE 3: BENCHMARK & DIAGNOSTIC UTILITIES
# ============================================================================
def run_benchmark_tool() -> None:
    """Benchmarks latency and raw throughput across the network."""
    Style.header("NETWORK & SSH THROUGHPUT BENCHMARK")
    cfg = load_config_defaults()

    host = Style.prompt("Target Host (Desktop IP)", cfg["desktop_host"])
    user = Style.prompt("Target User", cfg["desktop_user"])
    port = Style.prompt("SSH Port", str(cfg["ssh_port"]))
    key = Style.prompt("SSH Private Key", cfg["ssh_key"])
    key = os.path.expanduser(key)

    script = PROJECT_ROOT / "scripts" / "test_network_limits.sh"
    if script.exists():
        os.chmod(script, 0o755)
        # Execute script with user inputs piped
        subprocess.run(["bash", str(script)])
    else:
        # Fallback Python benchmark stream
        print(f"\n{Style.CYAN}Testing raw SSH stream to {user}@{host}...{Style.RESET}")
        cmd = (
            f"dd if=/dev/zero bs=1M count=1024 2>/dev/null | "
            f"ssh -i {key} -p {port} -o BatchMode=yes {user}@{host} 'cat > /dev/null'"
        )
        start = time.time()
        res = subprocess.run(cmd, shell=True)
        elapsed = time.time() - start

        if res.returncode == 0 and elapsed > 0:
            speed_mb = 1024.0 / elapsed
            print(f"\n{Style.GREEN}Transferred 1024 MB in {elapsed:.2f}s -> {speed_mb:.2f} MB/s{Style.RESET}")
        else:
            print(f"\n{Style.RED}Benchmark test failed. Check SSH keys and network connectivity.{Style.RESET}")

    input("\nPress Enter to return...")


def run_automated_tests() -> None:
    """Discovers and runs the full unit and integration test suite."""
    Style.header("RUNNING SYSTEM TEST SUITE")
    test_loader = unittest.defaultTestLoader
    suite = test_loader.discover(start_dir=str(PROJECT_ROOT / "tests"))
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)

    if res.wasSuccessful():
        print(f"\n{Style.GREEN}ALL TESTS PASSED SUCCESSFULLY!{Style.RESET}")
    else:
        print(f"\n{Style.RED}TEST FAILURES DETECTED: {len(res.failures)} failures, {len(res.errors)} errors.{Style.RESET}")

    input("\nPress Enter to return...")


# ============================================================================
# MODULE 4: INTERACTIVE WIZARD PORTAL
# ============================================================================
def interactive_portal() -> None:
    """Main interactive menu when script is invoked without CLI arguments."""
    while True:
        Style.header(f"{APP_NAME} v{APP_VERSION} - UNIFIED PORTAL")
        print("Select operational role for this machine:\n")
        print(f"  [{Style.GREEN}1{Style.RESET}] {Style.BOLD}SENDER (Laptop){Style.RESET}   - Synchronize partition data to remote Desktop")
        print(f"  [{Style.GREEN}2{Style.RESET}] {Style.BOLD}RECEIVER (Desktop){Style.RESET} - Manage storage, SQLite catalog, and audits")
        print(f"  [{Style.GREEN}3{Style.RESET}] {Style.BOLD}BENCHMARK{Style.RESET}          - Test network speed & SSH throughput")
        print(f"  [{Style.GREEN}4{Style.RESET}] {Style.BOLD}INSPECT DISKS{Style.RESET}      - List local block devices & partitions")
        print(f"  [{Style.GREEN}5{Style.RESET}] {Style.BOLD}RUN TESTS{Style.RESET}          - Execute full unit and integration suite")
        print(f"  [{Style.YELLOW}0{Style.RESET}] {Style.BOLD}EXIT{Style.RESET}")

        choice = Style.prompt("\nSelect mode", "1")

        if choice == "1":
            run_sender_workflow()
        elif choice == "2":
            run_receiver_menu()
        elif choice == "3":
            run_benchmark_tool()
        elif choice == "4":
            Style.header("LOCAL STORAGE PARTITIONS")
            detector = SystemDetector()
            CLIView().render_partitions_table(detector.list_block_devices())
            input("\nPress Enter to return...")
        elif choice == "5":
            run_automated_tests()
        elif choice in ("0", "exit", "q"):
            print("\nExiting. Goodbye!")
            sys.exit(0)


# ============================================================================
# MODULE 5: CLI ARGUMENT PARSER
# ============================================================================
def main() -> None:
    """Entry point parsing CLI arguments or falling back to interactive portal."""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} Unified Management Portal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Operational Subcommands")

    # SENDER subcommand
    p_send = subparsers.add_parser("send", help="Run sender client mode (Laptop)")
    p_send.add_argument("-s", "--source", help="Source partition mountpoint (e.g. /home)")
    p_send.add_argument("-H", "--desktop-host", help="Desktop IP or hostname")
    p_send.add_argument("-u", "--desktop-user", default="backup-user", help="Desktop SSH user")
    p_send.add_argument("-d", "--desktop-path", default="/srv/backups", help="Desktop storage path")
    p_send.add_argument("-p", "--port", type=int, default=DEFAULT_SSH_PORT, help="SSH port")
    p_send.add_argument("-i", "--key", default="~/.ssh/id_ed25519_backup", help="Private key path")
    p_send.add_argument("--tui", action="store_true", help="Enable Rich TUI dashboard")
    p_send.add_argument("--dry-run", action="store_true", help="Simulate backup without copying")
    p_send.add_argument("-z", "--compress", action="store_true", help="Enable compression")

    # RECEIVER subcommand
    p_recv = subparsers.add_parser("receive", help="Run receiver manager mode (Desktop)")
    p_recv.add_argument("--menu", action="store_true", help="Launch receiver interactive dashboard")

    # BENCHMARK subcommand
    subparsers.add_parser("benchmark", help="Run network latency and throughput benchmark")

    # TEST subcommand
    subparsers.add_parser("test", help="Execute complete automated test suite")

    # INSPECT subcommand
    subparsers.add_parser("inspect", help="Display local storage partitions")

    # If no arguments are provided, launch the interactive wizard
    if len(sys.argv) == 1:
        try:
            interactive_portal()
        except KeyboardInterrupt:
            print("\n\nOperation aborted by user. Exiting cleanly.")
            sys.exit(130)
        return

    args = parser.parse_args()

    if args.subcommand == "send":
        run_sender_workflow(
            source_override=args.source,
            host_override=args.desktop_host,
            user_override=args.desktop_user,
            dest_path_override=args.desktop_path,
            port_override=args.port,
            key_override=args.key,
            use_tui=args.tui,
            dry_run=args.dry_run,
            compress=args.compress,
        )
    elif args.subcommand == "receive":
        run_receiver_menu()
    elif args.subcommand == "benchmark":
        run_benchmark_tool()
    elif args.subcommand == "test":
        run_automated_tests()
    elif args.subcommand == "inspect":
        detector = SystemDetector()
        CLIView().render_partitions_table(detector.list_block_devices())


if __name__ == "__main__":
    main()
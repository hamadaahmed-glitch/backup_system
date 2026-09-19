"""
Standard Terminal Presentation Layer.
Constructed purely with the Python Standard Library (no external dependencies).
Supports ANSI coloring, dynamic progress bar rendering, and terminal resizing.
"""

import os
import shutil
import sys
import time
from typing import List, Optional

from client.core.progress_parser import TransferProgress
from client.core.rsync_runner import RsyncExecutionResult
from client.core.system_detect import PartitionInfo
from client.core.validator import ValidationResult
from client.core.verifier import VerificationReport


class CLIView:
    """Terminal UI renderer using standard ANSI escape codes."""

    # ANSI Formatting Constants
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    def __init__(self, use_color: bool = True) -> None:
        # Disable color automatically if stdout is redirected or piped
        self.use_color = use_color and sys.stdout.isatty()
        self._last_progress_line_len = 0

    def _color(self, text: str, color_code: str) -> str:
        if not self.use_color:
            return text
        return f"{color_code}{text}{self.RESET}"

    @staticmethod
    def format_bytes(size_bytes: int) -> str:
        """Converts bytes into human-readable metric strings."""
        if size_bytes < 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        unit_index = 0
        value = float(size_bytes)
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        return f"{value:.2f} {units[unit_index]}"

    def print_banner(self, title: str = "LINUX PARTITION BACKUP SYSTEM") -> None:
        """Renders an application header."""
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        divider = "=" * cols
        print(self._color(divider, self.CYAN))
        print(self._color(f"  {title}", self.BOLD + self.WHITE))
        print(self._color(divider, self.CYAN))

    def render_partitions_table(self, partitions: List[PartitionInfo]) -> None:
        """Renders discovered block devices and filesystems in an aligned table."""
        print(f"\n{self._color('DISCOVERED STORAGE PARTITIONS:', self.BOLD + self.CYAN)}")
        headers = ["Device", "FSType", "Mountpoint", "Used Space", "Total Size", "UUID"]
        row_format = "{:<16} {:<8} {:<18} {:<14} {:<14} {:<36}"

        print(self._color("-" * 110, self.DIM))
        print(self._color(row_format.format(*headers), self.BOLD))
        print(self._color("-" * 110, self.DIM))

        for p in partitions:
            used_str = self.format_bytes(p.used_bytes) if p.is_mounted else "N/A (unmounted)"
            total_str = self.format_bytes(p.total_bytes)
            mount_str = p.mountpoint or "[Not Mounted]"
            color = self.GREEN if p.is_mounted else self.DIM

            print(
                self._color(
                    row_format.format(
                        p.device_path,
                        p.fstype,
                        mount_str,
                        used_str,
                        total_str,
                        p.uuid[:36] if p.uuid else "None",
                    ),
                    color,
                )
            )
        print(self._color("-" * 110, self.DIM))

    def render_validation_result(self, res: ValidationResult) -> None:
        """Renders a pre-flight validation status summary."""
        print(f"\n{self._color('PRE-FLIGHT VALIDATION CHECKLIST:', self.BOLD + self.CYAN)}")

        if res.is_valid:
            print(f" [{self._color('✔ PASS', self.GREEN)}] Network target is online and reachable.")
            print(f" [{self._color('✔ PASS', self.GREEN)}] SSH authentication and keys accepted.")
            print(f" [{self._color('✔ PASS', self.GREEN)}] Remote rsync binary detected.")
            print(f" [{self._color('✔ PASS', self.GREEN)}] Storage capacity validated.")
            print(
                f"         - Required:  {self.format_bytes(res.source_used_bytes)} (+ safety headroom)\n"
                f"         - Available: {self.format_bytes(res.destination_available_bytes)}"
            )
        else:
            print(f" [{self._color('✖ FAIL', self.RED)}] Pre-flight validation checks rejected execution:")
            for err in res.errors:
                print(f"     - {self._color(err, self.RED)}")

        if res.warnings:
            print(f"\n{self._color('Warnings:', self.YELLOW)}")
            for w in res.warnings:
                print(f"  [!] {self._color(w, self.YELLOW)}")
        print()

    def render_progress(
        self,
        progress: TransferProgress,
        total_source_bytes: Optional[int] = None,
    ) -> None:
        """
        Renders a dynamic single-line terminal progress bar without line breaks.
        Uses `\r` to update smoothly on stdout.
        """
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))

        percent = max(0, min(100, progress.percentage))
        transferred_str = self.format_bytes(progress.bytes_transferred)

        if total_source_bytes and total_source_bytes > 0:
            target_str = self.format_bytes(total_source_bytes)
            size_stat = f"{transferred_str} / {target_str}"
        else:
            size_stat = transferred_str

        meta_info = f" | {size_stat} | {progress.speed_str} | ETA: {progress.eta_str}"
        
        # Calculate dynamic width for the bar characters
        fixed_text_len = 10 + len(meta_info)  # "[====] 100%" length
        bar_len = max(10, cols - fixed_text_len)

        completed_bars = int(bar_len * (percent / 100.0))
        remaining_bars = bar_len - completed_bars

        bar_visual = (
            self._color("=" * completed_bars, self.GREEN)
            + self._color(">", self.BOLD + self.GREEN)
            + self._color(" " * max(0, remaining_bars - 1), self.DIM)
        )

        progress_line = f"\r[{bar_visual}] {percent:>3}%{meta_info}"

        # Clean out line buffer if screen size resized down
        pad_len = max(0, self._last_progress_line_len - len(progress_line))
        sys.stdout.write(progress_line + (" " * pad_len))
        sys.stdout.flush()

        self._last_progress_line_len = len(progress_line)

    def render_summary(
        self,
        exec_result: RsyncExecutionResult,
        report: VerificationReport,
        duration_seconds: float,
    ) -> None:
        """Prints the final operation results and metrics."""
        # Ensure we move to a fresh newline after progress bar updates
        sys.stdout.write("\n\n")
        sys.stdout.flush()

        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        print(self._color("=" * cols, self.CYAN))

        if exec_result.was_interrupted:
            print(self._color("  TRANSFER INTERRUPTED BY USER / SIGNAL", self.BOLD + self.YELLOW))
            print(f"  Transferred up to abort: {self.format_bytes(exec_result.total_bytes_transferred)}")
            print("  Resume state preserved. Re-running the command will pick up where it stopped.")
            print(self._color("=" * cols, self.CYAN))
            return

        if not report.is_success:
            print(self._color("  BACKUP FAILED", self.BOLD + self.RED))
            print(f"  Status: {report.status_summary}")
            print(f"  Rsync Exit Code {report.exit_code}: {report.rsync_meaning}")
            if exec_result.error_message:
                print(f"  Error details:\n{self._color(exec_result.error_message, self.RED)}")
            print(self._color("=" * cols, self.CYAN))
            return

        # Success Output
        print(self._color("  BACKUP COMPLETED AND VERIFIED", self.BOLD + self.GREEN))
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)

        print(f"  Total Data Processed : {self.format_bytes(exec_result.total_bytes_transferred)}")
        print(f"  Elapsed Time         : {minutes}m {seconds}s")
        if duration_seconds > 0:
            avg_speed = exec_result.total_bytes_transferred / duration_seconds
            print(f"  Average Throughput   : {self.format_bytes(int(avg_speed))}/s")

        if report.source_file_count is not None and report.dest_file_count is not None:
            print(f"  Source Root Items    : {report.source_file_count}")
            print(f"  Remote Dest Items    : {report.dest_file_count}")

        print(f"  Integrity Audit      : {report.status_summary}")
        print(self._color("=" * cols, self.CYAN))
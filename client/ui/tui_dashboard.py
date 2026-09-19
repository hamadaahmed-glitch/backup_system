"""
Full Terminal User Interface (TUI) Dashboard.
Leverages the `rich` library when available for layout panels, 
styled progress tables, and performance monitoring.
Automatically falls back to CLIView if `rich` is not installed.
"""

import sys
import time
from typing import Optional

from client.core.progress_parser import TransferProgress
from client.core.rsync_runner import RsyncExecutionResult
from client.core.system_detect import PartitionInfo
from client.core.validator import ValidationResult
from client.core.verifier import VerificationReport
from client.ui.cli_view import CLIView

# Optional dependency check
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class TUIDashboard:
    """Provides a TUI dashboard using Rich, or falls back to standard CLIView."""

    def __init__(self, fallback_cli: Optional[CLIView] = None) -> None:
        self.fallback = fallback_cli or CLIView()
        self.has_rich = HAS_RICH
        if self.has_rich:
            self.console = Console()
            self._live: Optional[Live] = None
            self._layout: Optional[Layout] = None
            self._source_bytes_total = 0
            self._source_name = "N/A"
            self._target_name = "N/A"

    def is_rich_available(self) -> bool:
        """Returns True if the rich engine is installed and capable."""
        return self.has_rich and sys.stdout.isatty()

    def start_session(
        self,
        partition: PartitionInfo,
        destination_target: str,
        total_source_bytes: int,
    ) -> None:
        """Initializes the interactive TUI screen."""
        if not self.is_rich_available():
            self.fallback.print_banner()
            return

        self._source_bytes_total = total_source_bytes
        self._source_name = f"{partition.device_path} ({partition.mountpoint})"
        self._target_name = destination_target

        self._layout = Layout()
        self._layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", size=10),
            Layout(name="footer", size=3),
        )

        self._update_panels(
            TransferProgress(
                bytes_transferred=0,
                percentage=0,
                speed_str="0.00 MB/s",
                eta_str="--:--",
                files_transferred=0,
            )
        )

        self._live = Live(self._layout, console=self.console, refresh_per_second=4)
        self._live.start()

    def _update_panels(self, progress: TransferProgress) -> None:
        """Populates the layout components with real-time statistics."""
        if not self._layout:
            return

        # 1. Header Panel
        header_text = Text(
            f"BACKUP DASHBOARD: {self._source_name} ➔ {self._target_name}",
            style="bold white on blue",
            justify="center",
        )
        self._layout["header"].update(Panel(header_text, style="blue"))

        # 2. Main Metrics Table
        table = Table(expand=True, box=None)
        table.add_column("Metric", style="bold cyan", width=24)
        table.add_column("Status / Value", style="bold green")

        transferred_str = CLIView.format_bytes(progress.bytes_transferred)
        total_str = CLIView.format_bytes(self._source_bytes_total)

        table.add_row("Transfer Progress", f"{progress.percentage}% [{transferred_str} / {total_str}]")
        table.add_row("Transfer Speed", progress.speed_str)
        table.add_row("Estimated Time Left", progress.eta_str)
        if progress.files_transferred is not None:
            table.add_row("Files Processed", str(progress.files_transferred))
        if progress.to_check_str:
            table.add_row("Remaining Check Queue", progress.to_check_str)

        self._layout["main"].update(Panel(table, title="Active Operations", border_style="cyan"))

        # 3. Footer Panel
        footer_text = Text("Press Ctrl+C to safely pause/interrupt the rsync session", style="yellow")
        self._layout["footer"].update(Panel(footer_text, border_style="dim"))

    def update_progress(self, progress: TransferProgress) -> None:
        """Feeds a stream update to the active dashboard."""
        if not self.is_rich_available() or not self._live:
            self.fallback.render_progress(progress, self._source_bytes_total)
            return

        self._update_panels(progress)

    def close(self) -> None:
        """Tears down the live interface."""
        if self.is_rich_available() and self._live:
            self._live.stop()
            self._live = None

    def render_final_report(
        self,
        exec_result: RsyncExecutionResult,
        report: VerificationReport,
        duration: float,
    ) -> None:
        """Ensures TUI closes down before rendering final summary."""
        self.close()
        self.fallback.render_summary(exec_result, report, duration)
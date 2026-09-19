"""
Client UI Package.

Provides terminal presentation layers for partition inspection,
pre-flight validation checklists, streaming transfer progress, and reporting.
"""

from .cli_view import CLIView
from .tui_dashboard import TUIDashboard

__all__ = ["CLIView", "TUIDashboard"]
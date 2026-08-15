"""MCP ShipCheck: release-artifact probes for stdio MCP servers."""

from .compare import compare_snapshots
from .probe import probe_command

__all__ = ["compare_snapshots", "probe_command"]
__version__ = "0.1.0"

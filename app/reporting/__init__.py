"""Weekly RCJ business reporting.

The package deliberately keeps data collection, deterministic metric
calculation, AI commentary, rendering, and delivery separate.  The numerical
report never depends on the AI step.
"""

from app.reporting.periods import ReportWindow, build_report_window

__all__ = ["ReportWindow", "build_report_window"]

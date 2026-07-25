#!/usr/bin/env python3
"""One-shot Railway entrypoint for the RCJ Weekly Business Pulse."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.reporting.periods import build_report_window
from app.reporting.service import (
    DeliveryStateUnknown,
    run_weekly_business_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the RCJ weekly business report")
    parser.add_argument(
        "--window-end",
        help="Exclusive Friday cutoff in YYYY-MM-DD format",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and render without OpenAI, database state, or email delivery",
    )
    group.add_argument(
        "--force-resend",
        action="store_true",
        help="Intentionally send a new delivery generation",
    )
    parser.add_argument("--revision", type=int, help="Immutable report revision (>=1)")
    parser.add_argument(
        "--output",
        help="Preview directory or .html path; charts and text are written alongside it",
    )
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.revision is not None and args.revision < 1:
        parser.error("--revision must be at least 1")
    if args.force_resend and not args.window_end:
        parser.error("--force-resend requires an explicit --window-end")
    if args.window_end:
        try:
            parsed = date.fromisoformat(args.window_end)
            build_report_window(parsed)
        except ValueError as exc:
            parser.error(str(exc))

    app = create_app("production", start_scheduler=False)
    try:
        with app.app_context():
            result = run_weekly_business_report(
                window_end=args.window_end,
                revision=args.revision,
                dry_run=args.dry_run,
                output=args.output,
                force_resend=args.force_resend,
            )
        print(json.dumps(result.to_dict(), sort_keys=True))
        if result.status in {"disabled", "delivery_unknown"}:
            return 2
        return 0
    except DeliveryStateUnknown as exc:
        print(
            json.dumps(
                {
                    "status": "delivery_unknown",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

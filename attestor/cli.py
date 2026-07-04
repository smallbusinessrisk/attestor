"""
attestor.cli
------------
Command-line interface for the Attestor accountability layer.

Usage:
    attestor run        -- run the checker against the ledger DB
    attestor status     -- list commitments
    attestor watchdog   -- check the validator heartbeat
    attestor demo       -- run the fabrication demo

All commands accept --db (path to the ledger SQLite file) and --token
(verifier token; also reads ATTESTOR_VERIFIER_TOKEN env var).

Zero runtime dependencies — stdlib only.
"""
import argparse
import os
import sys
from pathlib import Path

# Ensure namespace-package imports (attestor.core.*, attestor.adapters.*)
# resolve correctly regardless of working directory.
_here = Path(__file__).resolve()
_workspace = _here.parent.parent.parent  # workspace/attestor/attestor/ → workspace/
if str(_workspace) not in sys.path:
    sys.path.insert(0, str(_workspace))


# ─── Command handlers ─────────────────────────────────────────────────────────

def cmd_run(args):
    """Run the checker against the ledger, verify pending evidence, print summary."""
    from attestor.adapters.store.sqlite import SQLiteLedger
    from attestor.adapters.notifier.stdout import StdoutNotifier
    from attestor.core.checker import CheckerAPI, SoDViolation

    token = args.token or os.environ.get("ATTESTOR_VERIFIER_TOKEN")
    if not token:
        print(
            "error: verifier token required — pass --token or set ATTESTOR_VERIFIER_TOKEN",
            file=sys.stderr,
        )
        sys.exit(1)

    os.environ["ATTESTOR_VERIFIER_TOKEN"] = token

    ledger = SQLiteLedger(args.db)
    notifier = StdoutNotifier()

    try:
        checker = CheckerAPI(
            ledger=ledger,
            verifier_id="attestor-cli",
            token=token,
            notifier=notifier,
        )
    except SoDViolation as e:
        print(f"error: SoD violation — {e}", file=sys.stderr)
        sys.exit(1)

    summary = checker.run()

    print(f"\nChecker run complete  [{args.db}]")
    print(f"  Passed:  {len(summary['passed'])}")
    print(f"  Failed:  {len(summary['failed'])}")
    print(f"  Skipped: {len(summary['skipped'])}")

    if summary["failed"]:
        print("\nFailed commitments:")
        for cid in summary["failed"]:
            c = ledger.get(cid)
            if c:
                print(f"  [{cid[:8]}...]  {c.task}")
                if c.blocker:
                    for line in c.blocker.split("\n"):
                        print(f"    {line}")

    if summary["passed"]:
        print("\nPassed commitments:")
        for cid in summary["passed"]:
            c = ledger.get(cid)
            if c:
                print(f"  [{cid[:8]}...]  {c.task}")


def cmd_status(args):
    """List commitments from the ledger, optionally filtered by status."""
    from attestor.adapters.store.sqlite import SQLiteLedger

    ledger = SQLiteLedger(args.db)
    status_filter = args.filter if args.filter != "all" else None
    commitments = ledger.list(status=status_filter)

    if not commitments:
        print(f"No commitments found in {args.db}.")
        return

    label = f"  {args.filter.upper()}" if args.filter != "all" else "  ALL"
    print(f"\nCommitments in {args.db}{label}")
    print(f"\n  {'ID':<10} {'STATUS':<12} {'MAKER':<22} TASK")
    print("  " + "─" * 76)
    for c in commitments:
        print(
            f"  {c.id[:8]:<10} {c.status:<12} {c.maker_id[:20]:<22}"
            f" {c.task[:40]}"
        )
    print(f"\n  Total: {len(commitments)}")


def cmd_watchdog(args):
    """Check the validator heartbeat — exits 1 if STALE or missing."""
    from attestor.core.watchdog import Watchdog
    from datetime import datetime, timezone

    watchdog = Watchdog(
        heartbeat_file=args.heartbeat_file,
        max_age_minutes=args.max_age,
    )

    last = watchdog.last_run()
    ok = watchdog.check()

    if ok:
        age_s = ""
        if last:
            age_min = int(
                (datetime.now(timezone.utc) - last).total_seconds() / 60
            )
            age_s = f"  ({age_min}m ago)"
        ts = last.isoformat() if last else "unknown"
        print(f"OK — validator last ran at {ts}{age_s}")
    else:
        if last:
            age_min = int(
                (datetime.now(timezone.utc) - last).total_seconds() / 60
            )
            print(
                f"STALE — validator last ran {age_min}m ago "
                f"(threshold: {args.max_age}m)"
            )
        else:
            print(
                f"STALE — no heartbeat found at "
                f"{args.heartbeat_file or 'default path'}"
            )
        sys.exit(1)


def cmd_demo(args):
    """Run the fabrication demo end-to-end."""
    demo_path = (
        Path(__file__).resolve().parent.parent
        / "examples"
        / "fabrication_demo"
        / "run_demo.py"
    )
    if not demo_path.exists():
        print(f"error: demo not found at {demo_path}", file=sys.stderr)
        sys.exit(1)

    import subprocess

    env = os.environ.copy()
    if "ATTESTOR_VERIFIER_TOKEN" not in env:
        env["ATTESTOR_VERIFIER_TOKEN"] = "demo-secret-token"

    result = subprocess.run([sys.executable, str(demo_path)], env=env)
    sys.exit(result.returncode)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="attestor",
        description=(
            "Attestor — accountability and verification layer for AI agent fleets.\n"
            'So that "done" means proven, not claimed.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        default="attestor.db",
        help="Path to the ledger SQLite database (default: attestor.db in cwd)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Verifier token (default: reads ATTESTOR_VERIFIER_TOKEN env var)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── run ──
    run_p = subparsers.add_parser(
        "run", help="Run the checker — verify pending commitments against reality"
    )
    run_p.set_defaults(func=cmd_run)

    # ── status ──
    status_p = subparsers.add_parser(
        "status", help="List commitments from the ledger DB"
    )
    status_p.add_argument(
        "--filter",
        default="all",
        choices=["all", "open", "in_progress", "completed", "failed", "overdue"],
        help="Filter by status (default: all)",
    )
    status_p.set_defaults(func=cmd_status)

    # ── watchdog ──
    wd_p = subparsers.add_parser(
        "watchdog", help="Check the validator heartbeat (exits 1 if STALE)"
    )
    wd_p.add_argument(
        "--heartbeat-file",
        default=None,
        dest="heartbeat_file",
        help="Path to heartbeat file (default: ATTESTOR_HEARTBEAT_FILE or /tmp/attestor_validator_heartbeat)",
    )
    wd_p.add_argument(
        "--max-age",
        type=int,
        default=60,
        dest="max_age",
        help="Max acceptable age in minutes (default: 60)",
    )
    wd_p.set_defaults(func=cmd_watchdog)

    # ── demo ──
    demo_p = subparsers.add_parser(
        "demo", help="Run the fabrication demo end-to-end"
    )
    demo_p.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

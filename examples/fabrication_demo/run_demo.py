#!/usr/bin/env python3
"""
Attestor — Fabrication Demo
============================

Watch a fabricating agent get caught by the independent validator in real time.

This demo runs end-to-end:
  1. A maker agent logs a commitment and claims to create a file.
  2. The maker fabricates — it writes plausible-looking evidence without
     actually creating the file.
  3. The independent validator re-measures reality.
  4. The validator catches the fabrication and writes VALIDATOR FAIL.

No agent frameworks required. Pure Python. Runs in under 5 seconds.

Usage:
    export ATTESTOR_VERIFIER_TOKEN=demo-secret-token
    python examples/fabrication_demo/run_demo.py
"""
import os
import sys
import time
import tempfile

# Allow running from repo root without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from attestor.adapters.store.sqlite import SQLiteLedger
from attestor.adapters.notifier.stdout import StdoutNotifier
from attestor.core.maker import MakerAPI
from attestor.core.checker import CheckerAPI
from attestor.core.evidence import EvidenceClaim
from attestor.core.watchdog import Watchdog

# ─── Setup ────────────────────────────────────────────────────────────────────

TOKEN = os.environ.get("ATTESTOR_VERIFIER_TOKEN", "demo-secret-token")
os.environ["ATTESTOR_VERIFIER_TOKEN"] = TOKEN   # Set for demo

DB = os.path.join(tempfile.gettempdir(), "attestor_demo.db")
if os.path.exists(DB):
    os.remove(DB)   # Fresh run

ledger = SQLiteLedger(db_path=DB)
notifier = StdoutNotifier()


def separator(title=""):
    w = 60
    if title:
        print(f"\n{'─' * 4} {title} {'─' * (w - len(title) - 6)}")
    else:
        print("─" * w)


def pause(msg=""):
    if msg:
        print(f"\n  {msg}")
    time.sleep(0.6)


# ─── Act 1: Maker agent logs a commitment ─────────────────────────────────────

separator("ACT 1 — Maker logs a commitment before starting work")

maker = MakerAPI(ledger=ledger, maker_id="builder-agent")

print("\n  builder-agent: 'Logging commitment before I start...'")
pause()

commitment = maker.commit(
    task="Create report file at /tmp/attestor_demo_report.txt with summary data",
    due_hours=1
)
print(f"\n  ✓ Commitment #{commitment.id[:8]}... created")
print(f"    Task:    {commitment.task}")
print(f"    Status:  {commitment.status}")
print(f"    Due:     {commitment.due_at[:19] if commitment.due_at else 'none'}")

pause("Maker marks work in-progress...")
maker.start(commitment.id)
print(f"  ✓ Status → in_progress")


# ─── Act 2: The maker fabricates ──────────────────────────────────────────────

separator("ACT 2 — Maker submits evidence (but fabricates the work)")

pause("builder-agent is 'working'...")

CLAIMED_FILE = "/tmp/attestor_demo_report.txt"
# THE FABRICATION: the maker submits evidence claiming the file exists
# but NEVER ACTUALLY CREATES IT.
print(f"\n  builder-agent: 'Done! Here is my evidence:'")
print(f"    File created: {CLAIMED_FILE} (1,842 bytes)")
print(f"    Contents: Monthly summary report — 47 records processed")
print(f"\n  ⚠️  (The file was never actually created — this is the fabrication)")

pause()

# Maker submits structured evidence claims
claims = [
    EvidenceClaim(
        kind="file_exists",
        description=f"Report file exists at {CLAIMED_FILE}",
        path=CLAIMED_FILE,
        min_bytes=100,
    )
]
maker.submit_evidence(commitment.id, claims)
print(f"\n  Evidence submitted for validator review.")


# ─── Act 3: The validator independently re-measures ───────────────────────────

separator("ACT 3 — Independent validator re-measures reality")

pause("validator-process starting independent verification...")
print()
print("  validator-process: 'I don't read the maker's transcript.'")
print("  validator-process: 'I check reality directly.'")
pause()

# SoD: CheckerAPI requires the verifier token — never in maker context
checker = CheckerAPI(
    ledger=ledger,
    verifier_id="validator-process",
    token=TOKEN,
    notifier=notifier,
)

watchdog = Watchdog()

print(f"\n  Checking: does {CLAIMED_FILE} exist?")
pause()
print(f"  $ ls -la {CLAIMED_FILE}")
pause()
print(f"  ls: {CLAIMED_FILE}: No such file or directory")
pause()


# ─── Act 4: VALIDATOR FAIL ────────────────────────────────────────────────────

separator("ACT 4 — Validator catches the fabrication")

summary = checker.run()
watchdog.heartbeat()

failed_id = summary["failed"][0] if summary["failed"] else None
if failed_id:
    result = ledger.get(commitment.id)
    print(f"\n  Commitment #{commitment.id[:8]}... → STATUS: {result.status.upper()}")
    print(f"\n  Blocker field written:")
    print(f"  ┌{'─' * 56}┐")
    for line in (result.blocker or "").split("\n"):
        print(f"  │ {line:<54} │")
    print(f"  └{'─' * 56}┘")


# ─── Act 5: SoD enforcement demo ──────────────────────────────────────────────

separator("ACT 5 — Maker cannot verify their own work (SoD)")

pause()
print("\n  builder-agent: 'Let me just mark this as done myself...'")
pause()

try:
    # Attempt to instantiate CheckerAPI without the verifier token
    bad_checker = CheckerAPI(
        ledger=ledger,
        verifier_id="builder-agent",
        token="i-dont-have-the-token",  # Maker doesn't have it
        notifier=notifier,
    )
    print("  ✗ SoD enforcement FAILED (this should not print)")
except Exception as e:
    print(f"  ✓ Blocked: {e}")


# ─── Summary ──────────────────────────────────────────────────────────────────

separator("RESULT")

print(f"""
  Commitments processed:  1
  Passed verification:    {len(summary['passed'])}
  Failed verification:    {len(summary['failed'])}
  Skipped (no evidence):  {len(summary['skipped'])}

  The fabrication was caught because:
  • The validator never reads the maker's claimed evidence
  • It independently checks {CLAIMED_FILE} — and finds nothing
  • VALIDATOR FAIL is written to the ledger's blocker field
  • The commitment stays visibly stuck until real work is done

  The maker could not self-verify because:
  • CheckerAPI requires ATTESTOR_VERIFIER_TOKEN
  • The token is never in the maker agent's environment
  • SoD is enforced at the permission layer, not the prompt

  Ledger: {DB}
""")

separator()

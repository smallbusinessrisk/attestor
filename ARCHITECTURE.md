# Attestor Architecture Guide

> "Done" means proven, not claimed.

Attestor is a thin accountability layer for AI agent fleets. It enforces
maker-checker separation — the agent that does the work can never be the
one that verifies it.

---

## The Three Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — POLICY LAYER                                         │
│  core/  (pure Python, zero dependencies)                        │
│                                                                  │
│   maker.py    → MakerAPI     (agent-side: commit, start, submit) │
│   checker.py  → CheckerAPI   (verifier: measure, pass, fail)    │
│   watchdog.py → Watchdog     (heartbeat: detect dead validators) │
│   ledger.py   → LedgerAdapter (abstract store interface)         │
│   evidence.py → EvidenceClaim / EvidenceResult (claim schema)   │
│   queue.py    → HumanCheckerQueue (non-binary claims)           │
│   shadow.py   → ShadowLogger (measure without enforcing)        │
└─────────────────────────────────────────────────────────────────┘
          │ implements                      │ injects
          ▼                                ▼
┌────────────────────┐          ┌────────────────────────────────┐
│  LAYER 2 — ADAPTERS│          │  LAYER 3 — HOST APP / AGENT    │
│  adapters/          │          │                                │
│                     │          │  Your agent:                   │
│  store/sqlite.py    │          │    maker = MakerAPI(ledger)    │
│  checks/file_check  │          │    c = maker.commit("task")    │
│  checks/http_check  │          │    maker.start(c.id)           │
│  checks/db_check    │          │    ... do work ...             │
│  checks/command_    │          │    maker.submit_evidence(...)  │
│  checks/git_check   │          │                                │
│  notifier/stdout    │          │  Your validator (separate env):│
│  notifier/discord   │          │    checker = CheckerAPI(...)   │
└────────────────────┘          │    checker.run()               │
                                └────────────────────────────────┘
```

---

## Data Flow

```
  MAKER PROCESS                    VERIFIER PROCESS
  (no VERIFIER_TOKEN)              (has VERIFIER_TOKEN)

  1. maker.commit()       ──→    Ledger (commitments table)
     task, due_at                 status = open

  2. maker.start()        ──→    Ledger
                                  status = in_progress

  3. agent does work
     ...

  4. maker.submit_evidence()  ──→  Ledger (metadata: pending_evidence JSON)

                               5. checker.run()
                                   reads pending_evidence
                                   independently measures each claim
                                        │
                                   ┌────┴────────────────────────────┐
                                   │  Mechanical checks              │
                                   │  file_check, http_check, etc.   │
                                   │                                 │
                                   │  Human claims (optional)        │
                                   │  → HumanCheckerQueue.enqueue()  │
                                   │                                 │
                                   │  Shadow mode (optional)         │
                                   │  → ShadowLogger.log()           │
                                   └────┬────────────────────────────┘
                                        │
                                   6a. All pass, no human pending:
                                       ledger.close()  ✓ VERIFIED
                                   6b. Any fail:
                                       ledger.fail()   ✗ VALIDATOR FAIL
                                   6c. Human reviews pending:
                                       left in_progress (blocked)
                                   6d. Shadow mode:
                                       nothing written to commitment

  Watchdog (separate process):
     Watchdog.heartbeat()  ──→  heartbeat file (timestamp)
     Watchdog.check()      ──→  raise alert if file > max_age_minutes old
```

---

## Directory Structure

```
attestor/
│
├── core/                       ← Policy layer. Pure Python, zero deps.
│   ├── evidence.py             ← EvidenceClaim / EvidenceResult dataclasses
│   ├── ledger.py               ← LedgerAdapter ABC + Commitment dataclass
│   ├── maker.py                ← MakerAPI — commit, start, submit_evidence
│   ├── checker.py              ← CheckerAPI — run, verify, reject
│   ├── watchdog.py             ← Watchdog — heartbeat, check, alert
│   ├── queue.py                ← HumanCheckerQueue — non-binary claim routing
│   └── shadow.py               ← ShadowLogger — measure without enforcing
│
├── adapters/
│   ├── checks/                 ← One file per check kind
│   │   ├── file_check.py       ← file_exists: stat the path
│   │   ├── http_check.py       ← http_status: urllib GET/HEAD
│   │   ├── db_check.py         ← row_count: SQLite COUNT(*)
│   │   ├── command_check.py    ← command_exit: subprocess exit code
│   │   └── git_check.py        ← git_commit: git cat-file -t
│   ├── store/
│   │   └── sqlite.py           ← SQLiteLedger — reference store impl
│   └── notifier/
│       ├── stdout.py           ← StdoutNotifier — print to terminal
│       └── discord.py          ← DiscordNotifier — post to webhook
│
├── attestor/
│   ├── __init__.py             ← Public API: MakerAPI, CheckerAPI, ...
│   └── cli.py                  ← `attestor` CLI entry point
│
├── tests/                      ← pytest test suite (stdlib only)
│   ├── test_evidence.py        ← All check adapters including git_check
│   ├── test_checker.py         ← SoD, verification, rejection flows
│   ├── test_maker.py           ← Commit, start, submit_evidence
│   ├── test_watchdog.py        ← Heartbeat, check, stale detection
│   ├── test_queue.py           ← Human review queue + checker routing
│   └── test_shadow.py          ← Shadow mode + ShadowLogger summary
│
├── examples/
│   └── fabrication_demo/
│       └── run_demo.py         ← End-to-end: fabrication attempt caught
│
├── schemas/                    ← JSON task schema examples
│   ├── build-task.json         ← Build: file + endpoint + test run
│   ├── deploy-task.json        ← Deploy: endpoint + git commit + DB row
│   └── content-task.json       ← Content: file + human quality review
│
├── ARCHITECTURE.md             ← This file
├── CONTRIBUTING.md             ← Extension guide (adapters, stores, notifiers)
├── SPEC.md                     ← Formal specification
└── README.md                   ← Quick start
```

---

## Quick Start — Wiring Attestor into Your Agent Pipeline

**Step 1 — Maker side (your agent process, no VERIFIER_TOKEN):**

```python
from attestor import MakerAPI, EvidenceClaim, SQLiteLedger

ledger = SQLiteLedger("attestor.db")
maker  = MakerAPI(ledger=ledger, maker_id="my-agent")

# Log the commitment BEFORE doing any work
c = maker.commit("Deploy the feature", due_hours=2)
maker.start(c.id)

# ... do the actual work ...

# Submit structured evidence for the validator to re-measure
maker.submit_evidence(c.id, [
    EvidenceClaim(
        kind="http_status",
        description="/health returns 200",
        url="http://localhost:8080/health",
        expected_status=200,
    ),
    EvidenceClaim(
        kind="file_exists",
        description="Build artifact created",
        path="/dist/app.tar.gz",
        min_bytes=10_000,
    ),
])
```

**Step 2 — Verifier side (separate process with VERIFIER_TOKEN):**

```python
import os
from attestor import CheckerAPI, SQLiteLedger

# ATTESTOR_VERIFIER_TOKEN must NEVER be set in the maker's environment
os.environ["ATTESTOR_VERIFIER_TOKEN"] = "your-secret-token"

ledger  = SQLiteLedger("attestor.db")
checker = CheckerAPI(
    ledger=ledger,
    verifier_id="validator-v1",
    token=os.environ["ATTESTOR_VERIFIER_TOKEN"],
)

summary = checker.run()
print(summary)  # {"passed": [...], "failed": [...], "skipped": [...]}
```

**Step 3 — Optional: shadow mode for baselining before enforcement:**

```python
checker = CheckerAPI(
    ledger=ledger, verifier_id="validator",
    token=token, shadow_mode=True,   # ← measure but never block
)
checker.run()  # all results written to shadow_log, no commitment touched

# Then from the CLI:
# attestor report --db attestor.db
```

---

## What Happens During a Verification Run

1. **`checker.run()`** calls `ledger.list(status="in_progress")`.
2. For each in-progress commitment, reads `metadata["pending_evidence"]` (JSON).
3. Deserializes each dict into an `EvidenceClaim` object.
4. **For each claim:**
   - If `requires_human_review=True` → enqueued to `HumanCheckerQueue`, skipped by mechanical checks.
   - Otherwise → dispatched to the matching check adapter (`file_check`, `http_check`, etc.).
   - Each adapter measures reality independently; never reads the maker's pasted output.
5. **Verdict:**
   - Any mechanical check fails → `ledger.fail()` writes `VALIDATOR FAIL` to `blocker`. Notifier fires.
   - Human reviews pending (and no mechanical failures) → commitment left `in_progress`. Human must resolve via `attestor review`.
   - All mechanical pass, no pending human reviews → `ledger.close()` writes `VERIFIED` to `evidence`.
   - Shadow mode → all results written to `shadow_log`; commitment status unchanged.
6. **Summary dict** returned: `{passed, failed, skipped, pending_human_review}`.

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| VERIFIER_TOKEN enforced at instantiation | Makers can't call CheckerAPI — enforced at code layer, not just prompt |
| Adapters measure independently | Fabricating "200 OK" in a transcript is trivial; measuring the live endpoint is not |
| Shadow mode before enforcement | Lets teams baseline reality before hard-blocking on verification failures |
| Human review queue | Some claims (content quality, UX review) can't be mechanically verified — they still get tracked |
| SQLite as reference store | Zero-dependency, portable; swap for Postgres via LedgerAdapter |
| stdlib-only core | No supply chain risk in the accountability layer itself |

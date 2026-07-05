# Contributing to Attestor

Attestor is a reference implementation — intentionally small, extensible by
design, and zero runtime dependencies. This guide covers the four extension
points and how to verify your changes.

---

## Running the tests

```bash
# From the repo root
python3 -m pytest tests/ -v
```

All tests use `tempfile` and `unittest.mock`. No external services needed.

To run the fabrication demo end-to-end:

```bash
export ATTESTOR_VERIFIER_TOKEN=demo-secret-token
python3 examples/fabrication_demo/run_demo.py
```

Or via the CLI:

```bash
cd /path/to/workspace
python3 -m attestor.cli demo   # sets ATTESTOR_VERIFIER_TOKEN automatically
```

---

## Adding a check adapter

A check adapter independently measures a single `EvidenceClaim` kind.

**1. Create the module** under `adapters/checks/`:

```python
# adapters/checks/my_check.py
from attestor.core.evidence import EvidenceClaim, EvidenceResult

def check(claim: EvidenceClaim) -> EvidenceResult:
    # Measure reality independently — never trust the maker's pasted output.
    # Return passed=True only if the measurement matches the claim.
    ...
    return EvidenceResult(
        claim=claim,
        passed=True,
        measured="what you actually observed",
        expected="what the claim said",
    )
```

**2. Register it in `CheckerAPI._measure()`** (`core/checker.py`):

```python
dispatch = {
    "file_exists":  file_check.check,
    "http_status":  http_check.check,
    "row_count":    db_check.check,
    "command_exit": command_check.check,
    "my_kind":      my_check.check,   # ← add here
}
```

Or inject it at runtime (no core changes needed):

```python
from adapters.checks import my_check

checker = CheckerAPI(
    ledger=ledger,
    verifier_id="validator",
    token=token,
    check_adapters={"my_kind": my_check},  # ← injected
)
```

**3. Write a test** in `tests/test_evidence.py` following the existing pattern.

---

## Adding a store adapter

A store adapter backs the commitments ledger with any database or service.

**1. Implement `LedgerAdapter`** (`core/ledger.py`):

```python
# adapters/store/my_store.py
from attestor.core.ledger import LedgerAdapter, Commitment
from typing import Optional

class MyStoreLedger(LedgerAdapter):
    def open(self, maker_id, task, due_at=None) -> Commitment: ...
    def start(self, commitment_id, maker_id) -> Commitment: ...
    def close(self, commitment_id, evidence, verified_by) -> Commitment: ...
    def fail(self, commitment_id, reason, rejected_by) -> Commitment: ...
    def get(self, commitment_id) -> Optional[Commitment]: ...
    def list(self, status=None, maker_id=None) -> list[Commitment]: ...
    def flag_overdue(self) -> list[Commitment]: ...
    def set_pending_evidence(self, commitment_id, evidence_json): ...
```

**2. Use it in place of `SQLiteLedger`:**

```python
from adapters.store.my_store import MyStoreLedger

ledger = MyStoreLedger(connection_string="...")
maker  = MakerAPI(ledger=ledger, maker_id="my-agent")
```

The core never imports a specific store — all backends are interchangeable.

---

## Adding a notifier adapter

A notifier fires alerts when the checker rejects a commitment or the watchdog
detects a stale validator.

**1. Implement the `alert` interface:**

```python
# adapters/notifier/my_notifier.py
class MyNotifier:
    def alert(self, message: str) -> None:
        # Send to Slack, PagerDuty, Discord, etc.
        ...
```

**2. Inject at runtime:**

```python
from adapters.notifier.my_notifier import MyNotifier

notifier = MyNotifier()
checker  = CheckerAPI(ledger=ledger, verifier_id="validator",
                      token=token, notifier=notifier)
watchdog = Watchdog(max_age_minutes=60, notifier=notifier)
```

Built-in notifiers: `adapters/notifier/stdout.py` (default),
`adapters/notifier/discord.py`.

---

---

## Using the human review queue

For claims that can't be mechanically verified (content quality, UI review,
business sign-off), set `requires_human_review=True` on the `EvidenceClaim`:

```python
from attestor import EvidenceClaim, HumanCheckerQueue, CheckerAPI, SQLiteLedger

ledger = SQLiteLedger("attestor.db")
queue  = HumanCheckerQueue(ledger)

# Maker submits a claim for human review
claim = EvidenceClaim(
    kind="human_review",
    description="Editorial quality check",
    requires_human_review=True,
    agent_output="The article draft is at /content/article.md",
)

# CheckerAPI automatically routes it to the queue
checker = CheckerAPI(ledger=ledger, verifier_id="validator",
                     token=token, queue=queue)
checker.run()  # claim enqueued, commitment left in_progress
```

Review and resolve via CLI:

```bash
attestor review list                               # see pending items
attestor review approve <item_id> --reviewer alice  # approve
attestor review reject  <item_id> --reviewer bob    # reject
```

---

## Using shadow mode

Shadow mode lets you measure discrepancy rates without blocking any agent work.
Deploy with shadow mode first, tune until failure rate is acceptable, then
switch to enforcement mode.

```python
checker = CheckerAPI(
    ledger=ledger, verifier_id="validator", token=token,
    shadow_mode=True,   # ← measure without blocking
)
checker.run()

# View results:
# attestor report --db attestor.db
```

Shadow log entries are written to the `shadow_log` table. The `ShadowLogger`
class can be used independently:

```python
from attestor import ShadowLogger, SQLiteLedger

ledger = SQLiteLedger("attestor.db")
shadow = ShadowLogger(ledger)
summary = shadow.summary()
print(f"Discrepancy rate: {summary['discrepancy_rate']:.1%}")
```

---

## Principles to keep

- **Zero runtime dependencies.** Core and CLI use stdlib only. Keep it that way.
- **Validator never reads pasted output.** Every check adapter must independently
  measure the world — not parse the maker's transcript.
- **SoD is enforced at the code layer.** `CheckerAPI` requires
  `ATTESTOR_VERIFIER_TOKEN` in the environment. Never put the token in maker
  agent context. Tests verify this can't be bypassed.
- **No commitment = no work started.** The first action is always `maker.commit()`.
- **Human review is still tracked.** Non-binary claims go into the queue, not
  into a black hole. Pending reviews block completion just like mechanical failures.
- **Shadow mode before enforcement.** Always baseline your discrepancy rate before
  enabling hard blocking. See `attestor report` for the readout.

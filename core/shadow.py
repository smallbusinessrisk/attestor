"""
attestor.core.shadow
--------------------
Shadow mode — measure reality without blocking anything.

Use ShadowLogger to record what the checker WOULD have done without
changing any commitment status. Run CheckerAPI with shadow_mode=True to
baseline your discrepancy rate before turning on hard enforcement.

Typical workflow:
    1. Deploy with shadow_mode=True for 1–2 weeks.
    2. Run `attestor report` to see would-have-failed rate.
    3. Fix your checks / agent outputs until rate < 5%.
    4. Switch to shadow_mode=False (enforcement on).

ShadowLogger never writes VALIDATOR FAIL and never changes commitment status.
"""
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ShadowLogger:
    """
    Records every check result to shadow_log without touching commitments.

    Backed by the ledger (duck-typed: expects SQLiteLedger or equivalent).

    Usage:
        checker = CheckerAPI(ledger=ledger, verifier_id="validator",
                             token=token, shadow_mode=True)
        checker.run()   # all results logged to shadow_log, nothing blocked

        shadow = ShadowLogger(ledger)
        summary = shadow.summary()
        print(summary["discrepancy_rate"])
    """

    def __init__(self, ledger):
        self.ledger = ledger

    def log(self, commitment_id: str, claim, result, would_block: bool) -> None:
        """
        Record a single check result to the shadow log.

        would_block=True means the result would have triggered VALIDATOR FAIL
        in enforcement mode; shadow mode did NOT write that blocker.
        """
        entry_id = str(uuid.uuid4())
        self.ledger.log_shadow(
            entry_id=entry_id,
            commitment_id=commitment_id,
            claim_kind=claim.kind,
            claim_description=claim.description,
            passed=result.passed,
            measured_value=result.measured,
            expected_value=result.expected,
            would_block=would_block,
            recorded_at=_now(),
        )

    def summary(self) -> dict:
        """
        Aggregate shadow log into a discrepancy report.

        Returns:
            total_measured: int
            would_have_passed: int
            would_have_failed: int
            discrepancy_rate: float  (0.0–1.0)
            by_kind: dict[str, {"measured": int, "would_have_failed": int}]
        """
        return self.ledger.shadow_summary()

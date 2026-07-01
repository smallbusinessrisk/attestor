"""
attestor.core.checker
---------------------
Checker (Validator) API — verifier only.

The checker is the independent party that re-measures reality after a maker
claims work is done. It does not read the maker's pasted evidence — it
independently hits the endpoint, counts the rows, stats the file.

Maker-checker principle: the agent that did the work cannot be the one
that verifies it. Enforced here by requiring a verifier_token that is never
present in the maker's environment.

SoD: the checker has write access to close/fail commitments.
     the maker does not.
"""
import os
from typing import Optional
from .ledger import LedgerAdapter, Commitment
from .evidence import EvidenceClaim, EvidenceResult, format_fail


VERIFIER_TOKEN_ENV = "ATTESTOR_VERIFIER_TOKEN"


class SoDViolation(PermissionError):
    """Raised when SoD enforcement fails — maker attempting verifier operations."""
    pass


class CheckerAPI:
    """
    The verifier-side interface. Only processes holding ATTESTOR_VERIFIER_TOKEN
    should instantiate this class.

    Usage:
        checker = CheckerAPI(ledger=SQLiteLedger("ledger.db"),
                             verifier_id="validator-process",
                             token=os.environ["ATTESTOR_VERIFIER_TOKEN"])
        checker.run()  # Picks up pending commitments, re-measures, closes or fails
    """

    def __init__(self, ledger: LedgerAdapter, verifier_id: str, token: str,
                 check_adapters=None, notifier=None):
        self._assert_token(token)
        self.ledger = ledger
        self.verifier_id = verifier_id
        self.check_adapters = check_adapters or {}
        self.notifier = notifier

    def _assert_token(self, token: str):
        """
        Enforce SoD at instantiation time.
        If the token is wrong or missing, the checker cannot be created.
        """
        expected = os.environ.get(VERIFIER_TOKEN_ENV)
        if not expected:
            raise SoDViolation(
                f"ATTESTOR_VERIFIER_TOKEN is not set. "
                f"The checker requires the verifier token — set it in the environment "
                f"of the validator process only. Never put it in maker agent context."
            )
        if token != expected:
            raise SoDViolation("Invalid verifier token. SoD enforced.")

    def verify(self, commitment_id: str, evidence: str) -> Commitment:
        """Close a commitment as verified-complete with measured evidence."""
        return self.ledger.close(
            commitment_id=commitment_id,
            evidence=evidence,
            verified_by=self.verifier_id
        )

    def reject(self, commitment_id: str, reason: str) -> Commitment:
        """Mark a commitment failed — validation did not pass."""
        c = self.ledger.fail(
            commitment_id=commitment_id,
            reason=reason,
            rejected_by=self.verifier_id
        )
        if self.notifier:
            self.notifier.alert(f"VALIDATOR FAIL #{commitment_id}: {reason}")
        return c

    def run(self) -> dict:
        """
        Main validator loop. Picks up commitments with pending evidence,
        re-measures each claim independently, and closes or fails them.

        Returns a summary: {passed: [...], failed: [...], skipped: [...]}
        """
        import json
        pending = self.ledger.list(status="in_progress")
        summary = {"passed": [], "failed": [], "skipped": []}

        for commitment in pending:
            raw = getattr(commitment, 'metadata', {}) or {}
            pending_evidence = raw.get("pending_evidence")
            if not pending_evidence:
                summary["skipped"].append(commitment.id)
                continue

            try:
                claims_data = json.loads(pending_evidence)
                claims = [self._deserialize_claim(c) for c in claims_data]
            except Exception as e:
                self.reject(commitment.id, f"Could not parse evidence claims: {e}")
                summary["failed"].append(commitment.id)
                continue

            results = [self._measure(claim) for claim in claims]
            failures = [r for r in results if not r.passed]

            if failures:
                fail_msg = format_fail(failures)
                self.reject(commitment.id, fail_msg)
                summary["failed"].append(commitment.id)
            else:
                measured = "; ".join(f"{r.claim.description}: {r.measured}" for r in results)
                self.verify(commitment.id, f"VERIFIED — {measured}")
                summary["passed"].append(commitment.id)

        return summary

    def _measure(self, claim: EvidenceClaim) -> EvidenceResult:
        """Independently measure a single evidence claim."""
        adapter = self.check_adapters.get(claim.kind)
        if adapter:
            return adapter.check(claim)
        # Fall back to built-in checks
        from ..adapters.checks import file_check, http_check, db_check, command_check
        dispatch = {
            "file_exists": file_check.check,
            "http_status": http_check.check,
            "row_count": db_check.check,
            "command_exit": command_check.check,
        }
        fn = dispatch.get(claim.kind)
        if fn:
            return fn(claim)
        return EvidenceResult(claim=claim, passed=False,
                              measured="no adapter", expected="check adapter",
                              detail=f"No check adapter for kind '{claim.kind}'")

    def _deserialize_claim(self, data: dict) -> EvidenceClaim:
        return EvidenceClaim(**{k: v for k, v in data.items()
                                if k in EvidenceClaim.__dataclass_fields__})

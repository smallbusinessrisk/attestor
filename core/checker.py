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

Shadow mode: pass shadow_mode=True to measure without enforcing. All results
are recorded to shadow_log but no commitment is failed or completed. Use this
to baseline your discrepancy rate before enabling enforcement.
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

    Shadow mode (measure without enforcing):
        checker = CheckerAPI(ledger=ledger, verifier_id="validator",
                             token=token, shadow_mode=True)
        checker.run()  # Measures but writes nothing to commitments
        # Then: attestor report   (reads shadow_log)

    Human review queue:
        queue = HumanCheckerQueue(ledger)
        checker = CheckerAPI(ledger=ledger, verifier_id="validator",
                             token=token, queue=queue)
        checker.run()  # Routes requires_human_review claims to queue
    """

    def __init__(self, ledger: LedgerAdapter, verifier_id: str, token: str,
                 check_adapters=None, notifier=None,
                 shadow_mode: bool = False, queue=None):
        self._assert_token(token)
        self.ledger = ledger
        self.verifier_id = verifier_id
        self.check_adapters = check_adapters or {}
        self.notifier = notifier
        self.shadow_mode = shadow_mode
        self.queue = queue

        if shadow_mode:
            from .shadow import ShadowLogger
            self._shadow = ShadowLogger(ledger)
        else:
            self._shadow = None

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

        Shadow mode: records results to shadow_log without touching commitments.
        Human review: routes requires_human_review claims to the queue.

        Returns a summary:
            {
                passed: [...commitment_ids],
                failed: [...commitment_ids],
                skipped: [...commitment_ids],
                pending_human_review: [...review_item_ids],
                shadow_mode: True   (only present when shadow_mode=True)
            }
        """
        import json
        pending = self.ledger.list(status="in_progress")
        summary = {
            "passed": [],
            "failed": [],
            "skipped": [],
            "pending_human_review": [],
        }

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
                if not self.shadow_mode:
                    self.reject(commitment.id, f"Could not parse evidence claims: {e}")
                    summary["failed"].append(commitment.id)
                else:
                    summary["skipped"].append(commitment.id)
                continue

            # Partition: human review vs mechanical
            human_claims = [c for c in claims if c.requires_human_review]
            mechanical_claims = [c for c in claims if not c.requires_human_review]

            # Run all mechanical checks
            results = [self._measure(claim) for claim in mechanical_claims]
            failures = [r for r in results if not r.passed]

            if self.shadow_mode and self._shadow:
                # Shadow mode — log everything, touch nothing
                for r in results:
                    self._shadow.log(
                        commitment_id=commitment.id,
                        claim=r.claim,
                        result=r,
                        would_block=not r.passed,
                    )
                summary["skipped"].append(commitment.id)

            else:
                # Enforcement mode — enqueue human reviews, fail or complete
                queued_ids = []
                if human_claims and self.queue:
                    for hc in human_claims:
                        item = self.queue.enqueue(
                            commitment_id=commitment.id,
                            claim_description=hc.description,
                            agent_output=hc.agent_output,
                        )
                        queued_ids.append(item.id)
                summary["pending_human_review"].extend(queued_ids)

                if failures:
                    # Mechanical check failed — reject immediately
                    fail_msg = format_fail(failures)
                    self.reject(commitment.id, fail_msg)
                    summary["failed"].append(commitment.id)
                elif queued_ids:
                    # Human reviews pending — do not complete, leave in_progress
                    summary["skipped"].append(commitment.id)
                else:
                    # All checks passed, no human reviews — complete
                    measured = "; ".join(
                        f"{r.claim.description}: {r.measured}" for r in results
                    ) or "all claims verified"
                    self.verify(commitment.id, f"VERIFIED — {measured}")
                    summary["passed"].append(commitment.id)

        if self.shadow_mode:
            summary["shadow_mode"] = True

        return summary

    def _measure(self, claim: EvidenceClaim) -> EvidenceResult:
        """Independently measure a single evidence claim."""
        adapter = self.check_adapters.get(claim.kind)
        if adapter:
            return adapter.check(claim)
        # Fall back to built-in checks
        from ..adapters.checks import file_check, http_check, db_check, command_check, git_check
        dispatch = {
            "file_exists":  file_check.check,
            "http_status":  http_check.check,
            "row_count":    db_check.check,
            "command_exit": command_check.check,
            "git_commit":   git_check.check,
        }
        fn = dispatch.get(claim.kind)
        if fn:
            return fn(claim)
        return EvidenceResult(
            claim=claim, passed=False,
            measured="no adapter",
            expected="check adapter",
            detail=f"No check adapter for kind '{claim.kind}'",
        )

    def _deserialize_claim(self, data: dict) -> EvidenceClaim:
        return EvidenceClaim(**{k: v for k, v in data.items()
                                if k in EvidenceClaim.__dataclass_fields__})

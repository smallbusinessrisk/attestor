"""
attestor.core.maker
-------------------
Maker API — available to any agent doing work.

Makers can:
  - commit()  log a new commitment before work begins
  - start()   mark their own commitment in_progress

Makers cannot:
  - verify or close any commitment (including their own)
  - write to the evidence store

SoD is enforced: start() raises PermissionError if the calling maker_id
does not match the commitment's original maker_id.
"""
from typing import Optional
from .ledger import LedgerAdapter, Commitment


class MakerAPI:
    """
    The maker-side interface. Inject into any agent that does work.

    Usage:
        maker = MakerAPI(ledger=SQLiteLedger("ledger.db"), maker_id="builder-agent")
        c = maker.commit("Add /health endpoint to API server", due_hours=2)
        maker.start(c.id)
        # ... do the work ...
        # Submit evidence for the validator to verify independently
        maker.submit_evidence(c.id, [
            EvidenceClaim(kind="http_status", description="/health returns 200",
                          url="http://localhost:8080/health", expected_status=200),
        ])
    """

    def __init__(self, ledger: LedgerAdapter, maker_id: str):
        self.ledger = ledger
        self.maker_id = maker_id

    def commit(self, task: str, due_hours: Optional[float] = None) -> Commitment:
        """
        Log a commitment before work begins.

        This is the pre-authorization step. No open commitment = the work has not started.
        Call this as the literal first action before doing anything else.
        """
        due_at = None
        if due_hours is not None:
            from datetime import datetime, timezone, timedelta
            due_at = (datetime.now(timezone.utc) + timedelta(hours=due_hours)).isoformat()
        c = self.ledger.open(maker_id=self.maker_id, task=task, due_at=due_at)
        return c

    def start(self, commitment_id: str) -> Commitment:
        """
        Mark your commitment in_progress.

        Raises PermissionError if commitment_id does not belong to this maker.
        SoD: you can only start your own work.
        """
        return self.ledger.start(commitment_id=commitment_id, maker_id=self.maker_id)

    def submit_evidence(self, commitment_id: str, claims: list) -> None:
        """
        Attach evidence claims to a commitment for the validator to verify.

        This does NOT close the commitment. The validator independently re-measures
        each claim and closes the commitment only if all checks pass.
        """
        import json
        c = self.ledger.get(commitment_id)
        if c is None:
            raise ValueError(f"Commitment {commitment_id} not found")
        if c.maker_id != self.maker_id:
            raise PermissionError(f"SoD: {self.maker_id} cannot submit evidence for {c.maker_id}'s commitment")
        # Store claims as JSON in metadata for the validator to pick up
        serialized = []
        for claim in claims:
            if hasattr(claim, '__dict__'):
                serialized.append(claim.__dict__)
            else:
                serialized.append(claim)
        # Write pending evidence via ledger metadata
        self.ledger.set_pending_evidence(commitment_id, json.dumps(serialized))

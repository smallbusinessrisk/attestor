"""
attestor.core.queue
-------------------
Human-checker review queue for claims that cannot be mechanically verified.

When an EvidenceClaim has requires_human_review=True, CheckerAPI routes it
here instead of running a mechanical check. Items stay pending until a human
reviewer approves or rejects them via the CLI (`attestor review`) or API.

Maker-checker principle: the agent that submitted the claim cannot be the
one that resolves the human review. Enforce this by restricting who can
call resolve().
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class HumanReviewItem:
    """A single claim awaiting human judgment."""
    id: str
    commitment_id: str
    claim_description: str
    agent_output: str           # What the agent submitted for this claim
    status: str                 # "pending" | "approved" | "rejected"
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]  # ISO UTC string
    created_at: str             # ISO UTC string


class HumanCheckerQueue:
    """
    Queue for evidence claims that require human judgment.

    Backed by the ledger (duck-typed: expects SQLiteLedger or equivalent).
    Wires into CheckerAPI automatically when passed as the queue= parameter.

    Usage:
        queue = HumanCheckerQueue(ledger)
        checker = CheckerAPI(ledger=ledger, verifier_id="validator",
                             token=token, queue=queue)
        checker.run()   # routes requires_human_review claims to the queue

        # Later — reviewer resolves via CLI or:
        item = queue.resolve(item_id, approved=True, reviewed_by="alice")
    """

    def __init__(self, ledger):
        self.ledger = ledger

    def enqueue(self, commitment_id: str, claim_description: str,
                agent_output: str) -> HumanReviewItem:
        """Add a claim to the pending review queue. Returns the new item."""
        item_id = _new_id()
        created_at = _now()
        self.ledger.enqueue_review(
            item_id=item_id,
            commitment_id=commitment_id,
            claim_description=claim_description,
            agent_output=agent_output,
            created_at=created_at,
        )
        return HumanReviewItem(
            id=item_id,
            commitment_id=commitment_id,
            claim_description=claim_description,
            agent_output=agent_output,
            status="pending",
            reviewed_by=None,
            reviewed_at=None,
            created_at=created_at,
        )

    def list_pending(self) -> list:
        """Return all pending (unresolved) review items."""
        return self.ledger.list_pending_reviews()

    def resolve(self, item_id: str, approved: bool,
                reviewed_by: str) -> HumanReviewItem:
        """
        Approve or reject a pending review item.

        approved=True  → status becomes "approved"
        approved=False → status becomes "rejected"

        Returns the updated HumanReviewItem.
        """
        reviewed_at = _now()
        self.ledger.resolve_review(
            item_id=item_id,
            approved=approved,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
        )
        return self.ledger.get_review(item_id)

    def pending_count(self, commitment_id: str) -> int:
        """Count pending review items for a specific commitment."""
        items = self.ledger.list_pending_reviews(commitment_id=commitment_id)
        return len(items)

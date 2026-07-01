"""
attestor.core.ledger
--------------------
The commitments ledger — the authoritative record of all work.

Schema is intentionally minimal. Adapters implement the storage backend.
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
import uuid


@dataclass
class Commitment:
    """A single unit of work, logged before it begins."""
    id: str
    maker_id: str           # Agent/process that owns this work
    task: str               # Human-readable description
    status: str             # open | in_progress | completed | failed | overdue
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None   # Must differ from maker_id (maker-checker)
    evidence: Optional[str] = None      # Verifier's independently measured evidence
    blocker: Optional[str] = None       # VALIDATOR FAIL reason if verification failed
    due_at: Optional[str] = None
    metadata: Optional[dict] = field(default_factory=dict)


class LedgerAdapter:
    """
    Abstract interface for the commitments store.

    Implement this to use any backend (SQLite, Postgres, JSON, etc.).
    The core never depends on a specific storage implementation.
    """

    def open(self, maker_id: str, task: str, due_at: Optional[str] = None) -> Commitment:
        """
        Create a new commitment. Called by the maker before work begins.
        No open commitment = the work has not started.
        """
        raise NotImplementedError

    def start(self, commitment_id: str, maker_id: str) -> Commitment:
        """
        Mark a commitment in_progress. Maker can only start their own commitment.
        SoD: raises PermissionError if maker_id != commitment.maker_id.
        """
        raise NotImplementedError

    def close(self, commitment_id: str, evidence: str, verified_by: str) -> Commitment:
        """
        Mark a commitment completed with verifier's independently measured evidence.
        Verifier only — enforced by the SoD boundary in the caller (CheckerAPI).
        """
        raise NotImplementedError

    def fail(self, commitment_id: str, reason: str, rejected_by: str) -> Commitment:
        """
        Mark a commitment failed. Verifier only.
        """
        raise NotImplementedError

    def get(self, commitment_id: str) -> Optional[Commitment]:
        """Retrieve a single commitment by ID."""
        raise NotImplementedError

    def list(self, status: Optional[str] = None, maker_id: Optional[str] = None) -> list[Commitment]:
        """List commitments, optionally filtered by status or maker."""
        raise NotImplementedError

    def flag_overdue(self) -> list[Commitment]:
        """Find open/in_progress commitments past their due_at and mark them overdue."""
        raise NotImplementedError


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())

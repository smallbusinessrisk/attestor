"""
Tests for the human-checker queue — core/queue.py + SQLiteLedger queue methods.

All tests use tempfile for ephemeral SQLite databases. Zero external deps.
"""
import os
import json
import tempfile
import pytest

from attestor.adapters.store.sqlite import SQLiteLedger
from attestor.core.queue import HumanCheckerQueue, HumanReviewItem
from attestor.core.evidence import EvidenceClaim


# ─── HumanCheckerQueue basics ─────────────────────────────────────────────────

class TestHumanCheckerQueue:

    def setup_method(self):
        self.fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        self.ledger = SQLiteLedger(self.db_path)
        self.queue = HumanCheckerQueue(self.ledger)

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_enqueue_creates_pending_item(self):
        item = self.queue.enqueue("commit-abc", "Quality check", "Output text here")
        assert isinstance(item, HumanReviewItem)
        assert item.id is not None and len(item.id) > 8
        assert item.commitment_id == "commit-abc"
        assert item.claim_description == "Quality check"
        assert item.agent_output == "Output text here"
        assert item.status == "pending"
        assert item.reviewed_by is None
        assert item.reviewed_at is None
        assert item.created_at is not None

    def test_list_pending_returns_only_pending(self):
        item1 = self.queue.enqueue("commit-1", "Check A", "output-a")
        item2 = self.queue.enqueue("commit-2", "Check B", "output-b")

        # Resolve item2
        self.queue.resolve(item2.id, approved=True, reviewed_by="alice")

        pending = self.queue.list_pending()
        assert len(pending) == 1
        assert pending[0].commitment_id == "commit-1"
        assert pending[0].status == "pending"

    def test_list_pending_returns_empty_when_none(self):
        pending = self.queue.list_pending()
        assert pending == []

    def test_resolve_marks_approved(self):
        item = self.queue.enqueue("commit-1", "Review this", "some output")
        resolved = self.queue.resolve(item.id, approved=True, reviewed_by="alice")
        assert resolved.status == "approved"
        assert resolved.reviewed_by == "alice"
        assert resolved.reviewed_at is not None
        assert resolved.id == item.id

    def test_resolve_marks_rejected(self):
        item = self.queue.enqueue("commit-1", "Review this", "some output")
        resolved = self.queue.resolve(item.id, approved=False, reviewed_by="bob")
        assert resolved.status == "rejected"
        assert resolved.reviewed_by == "bob"
        assert resolved.reviewed_at is not None

    def test_resolved_item_not_in_pending_list(self):
        item = self.queue.enqueue("commit-1", "Review", "output")
        self.queue.resolve(item.id, approved=True, reviewed_by="carol")
        assert len(self.queue.list_pending()) == 0

    def test_pending_count_per_commitment(self):
        self.queue.enqueue("commit-1", "Check A", "out-a")
        self.queue.enqueue("commit-1", "Check B", "out-b")
        self.queue.enqueue("commit-2", "Check C", "out-c")

        assert self.queue.pending_count("commit-1") == 2
        assert self.queue.pending_count("commit-2") == 1
        assert self.queue.pending_count("commit-none") == 0

    def test_pending_count_decrements_after_resolve(self):
        item = self.queue.enqueue("commit-1", "Check", "output")
        assert self.queue.pending_count("commit-1") == 1
        self.queue.resolve(item.id, approved=True, reviewed_by="dana")
        assert self.queue.pending_count("commit-1") == 0


# ─── Checker routing integration ──────────────────────────────────────────────

class TestCheckerQueueIntegration:

    def setup_method(self):
        self.fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        os.environ["ATTESTOR_VERIFIER_TOKEN"] = "test-queue-token"
        self.ledger = SQLiteLedger(self.db_path)
        self.queue = HumanCheckerQueue(self.ledger)

    def teardown_method(self):
        os.unlink(self.db_path)
        os.environ.pop("ATTESTOR_VERIFIER_TOKEN", None)

    def _make_in_progress(self, task: str, claims: list):
        """Helper: open, start, submit evidence, return commitment."""
        from attestor.core.maker import MakerAPI
        import dataclasses
        maker = MakerAPI(ledger=self.ledger, maker_id="test-maker")
        c = maker.commit(task)
        maker.start(c.id)
        self.ledger.set_pending_evidence(
            c.id, json.dumps([dataclasses.asdict(cl) for cl in claims])
        )
        return c

    def test_checker_routes_human_review_to_queue(self):
        """requires_human_review=True claims are enqueued, not run mechanically."""
        from attestor.core.checker import CheckerAPI

        claim = EvidenceClaim(
            kind="human_review",
            description="Editorial quality review",
            requires_human_review=True,
            agent_output="The article looks good and meets all criteria.",
        )
        c = self._make_in_progress("Write article", [claim])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="test-queue-token",
            queue=self.queue,
        )
        summary = checker.run()

        # Must appear in pending_human_review, not passed/failed
        assert len(summary["pending_human_review"]) == 1
        assert c.id not in summary["passed"]
        assert c.id not in summary["failed"]

    def test_commitment_not_completed_with_pending_review(self):
        """A commitment with unresolved human reviews must not be marked completed."""
        from attestor.core.checker import CheckerAPI

        claim = EvidenceClaim(
            kind="human_review",
            description="Human quality check",
            requires_human_review=True,
            agent_output="Completed successfully.",
        )
        c = self._make_in_progress("Quality-gated task", [claim])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="test-queue-token",
            queue=self.queue,
        )
        checker.run()

        updated = self.ledger.get(c.id)
        assert updated.status != "completed", (
            "Commitment with pending human reviews must remain in_progress"
        )

    def test_mixed_claims_mechanical_pass_human_pending(self):
        """If mechanical claims pass but human review pending, commitment stays in_progress."""
        from attestor.core.checker import CheckerAPI

        mechanical = EvidenceClaim(
            kind="command_exit",
            description="always passes",
            command="true",
            expected_exit=0,
        )
        human = EvidenceClaim(
            kind="human_review",
            description="Sign-off required",
            requires_human_review=True,
            agent_output="Deployed successfully.",
        )
        c = self._make_in_progress("Deploy with sign-off", [mechanical, human])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="test-queue-token",
            queue=self.queue,
        )
        summary = checker.run()

        updated = self.ledger.get(c.id)
        assert updated.status == "in_progress"
        assert len(summary["pending_human_review"]) == 1

    def test_mixed_claims_mechanical_fail_overrides(self):
        """If mechanical checks fail, commitment fails even with pending human review."""
        from attestor.core.checker import CheckerAPI

        mechanical = EvidenceClaim(
            kind="file_exists",
            description="nonexistent file",
            path="/this/file/does/not/exist/xyz_attestor.txt",
        )
        human = EvidenceClaim(
            kind="human_review",
            description="Review",
            requires_human_review=True,
            agent_output="Done.",
        )
        c = self._make_in_progress("Failing build", [mechanical, human])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="test-queue-token",
            queue=self.queue,
        )
        summary = checker.run()

        assert c.id in summary["failed"]
        updated = self.ledger.get(c.id)
        assert updated.status == "failed"

"""
Tests for MakerAPI — commit/start/evidence cycle and SoD enforcement.
"""
import os
import pytest
import tempfile

from attestor.adapters.store.sqlite import SQLiteLedger
from attestor.core.maker import MakerAPI
from attestor.core.evidence import EvidenceClaim


# ─── Helpers ──────────────────────────────────────────────────────────────────

def fresh_ledger():
    """Return (ledger, db_path) backed by a temp file; caller must unlink."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)           # SQLite creates it on first open
    return SQLiteLedger(db_path=path), path


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestCommit:
    def test_commit_returns_open_commitment(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            c = maker.commit("Build the thing")
            assert c.id is not None
            assert c.status == "open"
            assert c.maker_id == "agent-1"
            assert c.task == "Build the thing"
            assert c.started_at is None
        finally:
            os.unlink(path)

    def test_commit_with_due_hours_sets_due_at(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            c = maker.commit("Timed work", due_hours=2)
            assert c.due_at is not None
        finally:
            os.unlink(path)

    def test_multiple_commits_tracked_separately(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            c1 = maker.commit("Task one")
            c2 = maker.commit("Task two")
            assert c1.id != c2.id
            all_c = ledger.list()
            assert len(all_c) == 2
        finally:
            os.unlink(path)


class TestStart:
    def test_start_transitions_to_in_progress(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            c = maker.commit("Do work")
            c2 = maker.start(c.id)
            assert c2.status == "in_progress"
            assert c2.started_at is not None
        finally:
            os.unlink(path)

    def test_wrong_maker_cannot_start_another_commitment(self):
        """SoD: agent-b must not start agent-a's commitment."""
        ledger, path = fresh_ledger()
        try:
            maker_a = MakerAPI(ledger=ledger, maker_id="agent-a")
            maker_b = MakerAPI(ledger=ledger, maker_id="agent-b")
            c = maker_a.commit("Agent A's private work")
            with pytest.raises(PermissionError, match="SoD"):
                maker_b.start(c.id)
        finally:
            os.unlink(path)

    def test_start_nonexistent_commitment_raises(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            with pytest.raises(ValueError):
                maker.start("nonexistent-id-xyz")
        finally:
            os.unlink(path)


class TestSubmitEvidence:
    def test_submit_evidence_stores_pending_claims(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            c = maker.commit("Create a file")
            maker.start(c.id)
            claims = [
                EvidenceClaim(
                    kind="file_exists",
                    description="Output file exists",
                    path="/tmp/some_output.txt",
                    min_bytes=0,
                )
            ]
            maker.submit_evidence(c.id, claims)
            refreshed = ledger.get(c.id)
            assert refreshed.metadata.get("pending_evidence") is not None
        finally:
            os.unlink(path)

    def test_wrong_maker_cannot_submit_evidence(self):
        """SoD: agent-b must not submit evidence for agent-a's commitment."""
        ledger, path = fresh_ledger()
        try:
            maker_a = MakerAPI(ledger=ledger, maker_id="agent-a")
            maker_b = MakerAPI(ledger=ledger, maker_id="agent-b")
            c = maker_a.commit("Agent A's work")
            maker_a.start(c.id)
            claims = [
                EvidenceClaim(kind="file_exists", description="x", path="/tmp/x")
            ]
            with pytest.raises(PermissionError, match="SoD"):
                maker_b.submit_evidence(c.id, claims)
        finally:
            os.unlink(path)

    def test_submit_evidence_for_nonexistent_commitment_raises(self):
        ledger, path = fresh_ledger()
        try:
            maker = MakerAPI(ledger=ledger, maker_id="agent-1")
            with pytest.raises(ValueError):
                maker.submit_evidence(
                    "nonexistent-id",
                    [EvidenceClaim(kind="file_exists", description="x", path="/tmp/x")],
                )
        finally:
            os.unlink(path)

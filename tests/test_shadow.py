"""
Tests for shadow mode — core/shadow.py + SQLiteLedger shadow methods.

All tests use tempfile for ephemeral SQLite databases. Zero external deps.
"""
import os
import json
import tempfile
import pytest

from attestor.adapters.store.sqlite import SQLiteLedger
from attestor.core.shadow import ShadowLogger
from attestor.core.evidence import EvidenceClaim, EvidenceResult


# ─── ShadowLogger basics ──────────────────────────────────────────────────────

class TestShadowLogger:

    def setup_method(self):
        self.fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        self.ledger = SQLiteLedger(self.db_path)
        self.shadow = ShadowLogger(self.ledger)

    def teardown_method(self):
        os.unlink(self.db_path)

    def _make_result(self, kind: str, passed: bool, desc: str = "check") -> tuple:
        claim = EvidenceClaim(kind=kind, description=desc)
        result = EvidenceResult(
            claim=claim, passed=passed,
            measured="observed" if passed else "NOT as expected",
            expected="expected value",
        )
        return claim, result

    def test_log_writes_to_shadow_log(self):
        """ShadowLogger.log() should write an entry that shows up in summary."""
        claim, result = self._make_result("command_exit", passed=True)
        self.shadow.log("commit-1", claim, result, would_block=False)

        summary = self.shadow.summary()
        assert summary["total_measured"] == 1
        assert summary["would_have_passed"] == 1
        assert summary["would_have_failed"] == 0

    def test_log_failed_result(self):
        """A failed result should increment would_have_failed."""
        claim, result = self._make_result("http_status", passed=False)
        self.shadow.log("commit-1", claim, result, would_block=True)

        summary = self.shadow.summary()
        assert summary["total_measured"] == 1
        assert summary["would_have_passed"] == 0
        assert summary["would_have_failed"] == 1

    def test_summary_empty_returns_zeros(self):
        summary = self.shadow.summary()
        assert summary["total_measured"] == 0
        assert summary["would_have_passed"] == 0
        assert summary["would_have_failed"] == 0
        assert summary["discrepancy_rate"] == 0.0
        assert summary["by_kind"] == {}

    def test_summary_discrepancy_rate(self):
        """discrepancy_rate = would_have_failed / total_measured."""
        for i in range(3):
            claim, result = self._make_result("file_exists", passed=True)
            self.shadow.log("commit-1", claim, result, would_block=False)
        for i in range(1):
            claim, result = self._make_result("file_exists", passed=False)
            self.shadow.log("commit-1", claim, result, would_block=True)

        summary = self.shadow.summary()
        assert summary["total_measured"] == 4
        assert summary["would_have_passed"] == 3
        assert summary["would_have_failed"] == 1
        assert summary["discrepancy_rate"] == pytest.approx(0.25, abs=0.001)

    def test_summary_by_kind(self):
        """by_kind aggregates counts per check type."""
        for _ in range(2):
            claim, result = self._make_result("http_status", passed=True)
            self.shadow.log("commit-1", claim, result, would_block=False)
        for _ in range(3):
            claim, result = self._make_result("file_exists", passed=False)
            self.shadow.log("commit-2", claim, result, would_block=True)

        summary = self.shadow.summary()
        assert "http_status" in summary["by_kind"]
        assert "file_exists" in summary["by_kind"]
        assert summary["by_kind"]["http_status"]["measured"] == 2
        assert summary["by_kind"]["http_status"]["would_have_failed"] == 0
        assert summary["by_kind"]["file_exists"]["measured"] == 3
        assert summary["by_kind"]["file_exists"]["would_have_failed"] == 3


# ─── CheckerAPI shadow mode integration ───────────────────────────────────────

class TestCheckerShadowMode:

    def setup_method(self):
        self.fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        os.environ["ATTESTOR_VERIFIER_TOKEN"] = "shadow-test-token"
        self.ledger = SQLiteLedger(self.db_path)

    def teardown_method(self):
        os.unlink(self.db_path)
        os.environ.pop("ATTESTOR_VERIFIER_TOKEN", None)

    def _make_in_progress(self, task: str, claims: list):
        from attestor.core.maker import MakerAPI
        import dataclasses
        maker = MakerAPI(ledger=self.ledger, maker_id="test-maker")
        c = maker.commit(task)
        maker.start(c.id)
        self.ledger.set_pending_evidence(
            c.id, json.dumps([dataclasses.asdict(cl) for cl in claims])
        )
        return c

    def test_shadow_mode_does_not_write_blocker(self):
        """In shadow mode, a failing claim must NOT write VALIDATOR FAIL to commitment."""
        from attestor.core.checker import CheckerAPI

        claim = EvidenceClaim(
            kind="file_exists",
            description="nonexistent file",
            path="/this/does/not/exist/attestor_shadow_test.txt",
        )
        c = self._make_in_progress("Shadow task", [claim])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="shadow-test-token",
            shadow_mode=True,
        )
        checker.run()

        updated = self.ledger.get(c.id)
        assert updated.blocker is None, (
            "shadow_mode must never write a blocker to the commitment"
        )

    def test_shadow_mode_does_not_change_status_to_failed(self):
        """In shadow mode, failing claims must not change status to 'failed'."""
        from attestor.core.checker import CheckerAPI

        claim = EvidenceClaim(
            kind="file_exists",
            description="nonexistent file",
            path="/no/such/file/xyz_shadow.txt",
        )
        c = self._make_in_progress("Shadow fail task", [claim])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="shadow-test-token",
            shadow_mode=True,
        )
        checker.run()

        updated = self.ledger.get(c.id)
        assert updated.status == "in_progress", (
            "shadow_mode must not transition commitment to 'failed'"
        )

    def test_shadow_mode_writes_to_shadow_log(self):
        """Every result in shadow mode must be written to shadow_log."""
        from attestor.core.checker import CheckerAPI

        claim = EvidenceClaim(
            kind="command_exit",
            description="always passes",
            command="true",
            expected_exit=0,
        )
        self._make_in_progress("Shadow pass task", [claim])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="shadow-test-token",
            shadow_mode=True,
        )
        checker.run()

        shadow = ShadowLogger(self.ledger)
        summary = shadow.summary()
        assert summary["total_measured"] == 1

    def test_shadow_mode_summary_flag_in_run_result(self):
        """checker.run() in shadow mode must include shadow_mode=True in summary."""
        from attestor.core.checker import CheckerAPI

        claim = EvidenceClaim(
            kind="command_exit",
            description="exit 0",
            command="true",
        )
        self._make_in_progress("Shadow flag task", [claim])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="shadow-test-token",
            shadow_mode=True,
        )
        summary = checker.run()

        assert summary.get("shadow_mode") is True

    def test_shadow_mode_correct_rates(self):
        """ShadowLogger.summary() returns correct pass/fail counts after checker.run()."""
        from attestor.core.checker import CheckerAPI

        passing = EvidenceClaim(
            kind="command_exit", description="passes", command="true", expected_exit=0
        )
        failing = EvidenceClaim(
            kind="file_exists", description="fails",
            path="/totally/missing/file_shadow_abc.txt"
        )
        self._make_in_progress("Mixed shadow", [passing, failing])

        checker = CheckerAPI(
            ledger=self.ledger,
            verifier_id="validator",
            token="shadow-test-token",
            shadow_mode=True,
        )
        checker.run()

        shadow = ShadowLogger(self.ledger)
        summary = shadow.summary()
        assert summary["total_measured"] == 2
        assert summary["would_have_passed"] == 1
        assert summary["would_have_failed"] == 1
        assert summary["discrepancy_rate"] == pytest.approx(0.5, abs=0.001)


# ─── CLI `attestor report` ────────────────────────────────────────────────────

class TestReportCLI:
    """Smoke-test: attestor report command prints summary without error."""

    def setup_method(self):
        self.fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_report_empty_db_no_error(self, capsys):
        """report on empty shadow_log should print cleanly and exit 0."""
        from attestor.attestor.cli import cmd_report
        import argparse

        args = argparse.Namespace(db=self.db_path)
        cmd_report(args)

        captured = capsys.readouterr()
        assert "Shadow Mode Report" in captured.out
        # Should not crash or print to stderr
        assert captured.err == ""

    def test_report_shows_counts(self, capsys):
        """report with shadow log entries should show correct totals."""
        from attestor.attestor.cli import cmd_report
        import argparse

        # Pre-populate shadow_log
        ledger = SQLiteLedger(self.db_path)
        shadow = ShadowLogger(ledger)
        for _ in range(3):
            claim = EvidenceClaim(kind="http_status", description="check")
            result = EvidenceResult(claim=claim, passed=True, measured="200", expected="200")
            shadow.log("commit-x", claim, result, would_block=False)
        for _ in range(2):
            claim = EvidenceClaim(kind="http_status", description="check")
            result = EvidenceResult(claim=claim, passed=False, measured="500", expected="200")
            shadow.log("commit-x", claim, result, would_block=True)

        args = argparse.Namespace(db=self.db_path)
        cmd_report(args)

        captured = capsys.readouterr()
        assert "5" in captured.out            # total_measured
        assert "3" in captured.out            # would_have_passed
        assert "2" in captured.out            # would_have_failed
        assert captured.err == ""

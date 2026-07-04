"""
Tests for CheckerAPI — SoD enforcement and independent verification.
"""
import os
import pytest
import tempfile

from attestor.adapters.store.sqlite import SQLiteLedger
from attestor.core.maker import MakerAPI
from attestor.core.checker import CheckerAPI, SoDViolation
from attestor.core.evidence import EvidenceClaim


# ─── Helpers ──────────────────────────────────────────────────────────────────

VALID_TOKEN = "test-verifier-token-abc123"


def fresh_ledger():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return SQLiteLedger(db_path=path), path


def make_checker(ledger, token=VALID_TOKEN):
    os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN
    return CheckerAPI(ledger=ledger, verifier_id="test-validator", token=token)


# ─── SoD enforcement ──────────────────────────────────────────────────────────

class TestSoDEnforcement:
    def test_missing_env_token_raises_sod_violation(self):
        """CheckerAPI cannot be instantiated if ATTESTOR_VERIFIER_TOKEN is not set."""
        ledger, path = fresh_ledger()
        try:
            os.environ.pop("ATTESTOR_VERIFIER_TOKEN", None)
            with pytest.raises(SoDViolation):
                CheckerAPI(ledger=ledger, verifier_id="validator", token="anything")
        finally:
            os.unlink(path)

    def test_wrong_token_raises_sod_violation(self):
        """CheckerAPI refuses an incorrect token even when env is set."""
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN
            with pytest.raises(SoDViolation, match="Invalid verifier token"):
                CheckerAPI(
                    ledger=ledger, verifier_id="validator", token="totally-wrong"
                )
        finally:
            os.unlink(path)

    def test_correct_token_instantiates_successfully(self):
        """CheckerAPI instantiates with the correct token and env var."""
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN
            checker = CheckerAPI(
                ledger=ledger, verifier_id="validator", token=VALID_TOKEN
            )
            assert checker is not None
            assert checker.verifier_id == "validator"
        finally:
            os.unlink(path)


# ─── Verification logic ───────────────────────────────────────────────────────

class TestCheckerVerification:
    def test_fabrication_caught_file_not_found(self):
        """
        Maker claims a file exists, never creates it.
        Checker independently checks — file not found → VALIDATOR FAIL.
        """
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN

            maker = MakerAPI(ledger=ledger, maker_id="fabricator")
            c = maker.commit("Create output file")
            maker.start(c.id)

            claims = [
                EvidenceClaim(
                    kind="file_exists",
                    description="Output at /nonexistent/totally_fake_output.txt",
                    path="/nonexistent/totally_fake_output.txt",
                    min_bytes=100,
                )
            ]
            maker.submit_evidence(c.id, claims)

            checker = make_checker(ledger)
            summary = checker.run()

            assert c.id in summary["failed"]
            assert c.id not in summary["passed"]

            result = ledger.get(c.id)
            assert result.status == "failed"
            assert result.blocker is not None
            assert "VALIDATOR FAIL" in result.blocker
        finally:
            os.unlink(path)

    def test_real_evidence_passes(self):
        """
        Maker creates a real file and submits correct evidence.
        Checker verifies → commitment completed.
        """
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN

            maker = MakerAPI(ledger=ledger, maker_id="honest-agent")
            c = maker.commit("Create a real file")
            maker.start(c.id)

            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".txt"
            ) as f:
                f.write("real content here\n" * 10)
                real_file = f.name

            try:
                claims = [
                    EvidenceClaim(
                        kind="file_exists",
                        description="Real output file",
                        path=real_file,
                        min_bytes=10,
                    )
                ]
                maker.submit_evidence(c.id, claims)

                checker = make_checker(ledger)
                summary = checker.run()

                assert c.id in summary["passed"]
                assert c.id not in summary["failed"]

                result = ledger.get(c.id)
                assert result.status == "completed"
                assert result.blocker is None
                assert result.verified_by == "test-validator"
                assert result.verified_at is not None
            finally:
                os.unlink(real_file)
        finally:
            os.unlink(path)

    def test_commitment_with_no_evidence_skipped(self):
        """Commitments in_progress but with no pending evidence are skipped."""
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN

            maker = MakerAPI(ledger=ledger, maker_id="agent")
            c = maker.commit("Work with no evidence")
            maker.start(c.id)
            # Deliberately no submit_evidence call

            checker = make_checker(ledger)
            summary = checker.run()

            assert c.id in summary["skipped"]
            assert c.id not in summary["passed"]
            assert c.id not in summary["failed"]
        finally:
            os.unlink(path)

    def test_open_commitment_not_processed(self):
        """
        Open commitments (not yet started) are not picked up by the checker.
        The checker only processes in_progress commitments.
        """
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN

            maker = MakerAPI(ledger=ledger, maker_id="agent")
            c = maker.commit("Not started yet")
            # No start() call

            checker = make_checker(ledger)
            summary = checker.run()

            # Should not appear in any list
            all_ids = summary["passed"] + summary["failed"] + summary["skipped"]
            assert c.id not in all_ids
        finally:
            os.unlink(path)

    def test_mixed_evidence_fails_if_any_claim_fails(self):
        """
        If a commitment has two claims and one fails, the whole commitment fails.
        """
        ledger, path = fresh_ledger()
        try:
            os.environ["ATTESTOR_VERIFIER_TOKEN"] = VALID_TOKEN

            maker = MakerAPI(ledger=ledger, maker_id="agent")
            c = maker.commit("Create file and nonexistent file")
            maker.start(c.id)

            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".txt"
            ) as f:
                f.write("exists\n")
                real_file = f.name

            try:
                claims = [
                    EvidenceClaim(
                        kind="file_exists",
                        description="Real file",
                        path=real_file,
                        min_bytes=1,
                    ),
                    EvidenceClaim(
                        kind="file_exists",
                        description="Fake file",
                        path="/nonexistent/fake.txt",
                        min_bytes=1,
                    ),
                ]
                maker.submit_evidence(c.id, claims)

                checker = make_checker(ledger)
                summary = checker.run()

                assert c.id in summary["failed"]

                result = ledger.get(c.id)
                assert result.status == "failed"
                assert "VALIDATOR FAIL" in (result.blocker or "")
            finally:
                os.unlink(real_file)
        finally:
            os.unlink(path)

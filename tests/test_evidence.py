"""
Tests for check adapters — file_check, http_check, db_check, command_check.

All tests use tempfile and unittest.mock — zero external dependencies.
"""
import os
import sqlite3
import tempfile
import pytest
import urllib.error
from unittest.mock import patch, MagicMock

from attestor.core.evidence import EvidenceClaim
from attestor.adapters.checks import file_check, http_check, db_check, command_check


# ─── file_check ───────────────────────────────────────────────────────────────

class TestFileCheck:
    def test_existing_file_passes(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("hello attestor\n")
            path = f.name
        try:
            claim = EvidenceClaim(
                kind="file_exists", description="existing file", path=path
            )
            result = file_check.check(claim)
            assert result.passed is True
        finally:
            os.unlink(path)

    def test_missing_file_fails(self):
        claim = EvidenceClaim(
            kind="file_exists",
            description="missing file",
            path="/nonexistent/path/nope_xyz123.txt",
        )
        result = file_check.check(claim)
        assert result.passed is False

    def test_file_large_enough_passes(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("a" * 500)
            path = f.name
        try:
            claim = EvidenceClaim(
                kind="file_exists",
                description="large enough file",
                path=path,
                min_bytes=100,
            )
            result = file_check.check(claim)
            assert result.passed is True
        finally:
            os.unlink(path)

    def test_file_too_small_fails(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("tiny")
            path = f.name
        try:
            claim = EvidenceClaim(
                kind="file_exists",
                description="file too small",
                path=path,
                min_bytes=100_000,
            )
            result = file_check.check(claim)
            assert result.passed is False
        finally:
            os.unlink(path)

    def test_no_path_fails(self):
        claim = EvidenceClaim(kind="file_exists", description="no path given")
        result = file_check.check(claim)
        assert result.passed is False

    def test_result_contains_claim(self):
        claim = EvidenceClaim(
            kind="file_exists",
            description="contains claim ref",
            path="/tmp/missing_test_file.txt",
        )
        result = file_check.check(claim)
        assert result.claim is claim


# ─── http_check ───────────────────────────────────────────────────────────────

class TestHttpCheck:
    def _mock_response(self, status_code):
        resp = MagicMock()
        resp.status = status_code
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_expected_200_passes(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
            claim = EvidenceClaim(
                kind="http_status",
                description="API health check",
                url="http://example.com/health",
                expected_status=200,
            )
            result = http_check.check(claim)
            assert result.passed is True

    def test_unexpected_status_fails(self):
        err = urllib.error.HTTPError(
            url="http://example.com/health",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            claim = EvidenceClaim(
                kind="http_status",
                description="should be 200 not 404",
                url="http://example.com/health",
                expected_status=200,
            )
            result = http_check.check(claim)
            assert result.passed is False
            assert "404" in result.measured

    def test_expected_404_passes(self):
        err = urllib.error.HTTPError(
            url="http://example.com/gone",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            claim = EvidenceClaim(
                kind="http_status",
                description="endpoint returns 404 as expected",
                url="http://example.com/gone",
                expected_status=404,
            )
            result = http_check.check(claim)
            assert result.passed is True

    def test_connection_error_fails(self):
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            claim = EvidenceClaim(
                kind="http_status",
                description="unreachable host",
                url="http://localhost:19999/health",
                expected_status=200,
            )
            result = http_check.check(claim)
            assert result.passed is False
            assert "error" in result.measured.lower()

    def test_no_url_fails(self):
        claim = EvidenceClaim(
            kind="http_status", description="missing url", expected_status=200
        )
        result = http_check.check(claim)
        assert result.passed is False

    def test_default_expected_status_is_200(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
            claim = EvidenceClaim(
                kind="http_status",
                description="default expected 200",
                url="http://example.com/",
            )
            result = http_check.check(claim)
            assert result.passed is True


# ─── db_check ─────────────────────────────────────────────────────────────────

class TestDbCheck:
    def _make_db(self, rows=3) -> str:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        )
        for i in range(rows):
            conn.execute("INSERT INTO items (name) VALUES (?)", (f"item-{i}",))
        conn.commit()
        conn.close()
        return path

    def test_sufficient_rows_passes(self):
        path = self._make_db(rows=5)
        try:
            claim = EvidenceClaim(
                kind="row_count",
                description="items table has >= 3 rows",
                db_path=path,
                table="items",
                min_rows=3,
            )
            result = db_check.check(claim)
            assert result.passed is True
        finally:
            os.unlink(path)

    def test_insufficient_rows_fails(self):
        path = self._make_db(rows=1)
        try:
            claim = EvidenceClaim(
                kind="row_count",
                description="items table has >= 10 rows",
                db_path=path,
                table="items",
                min_rows=10,
            )
            result = db_check.check(claim)
            assert result.passed is False
        finally:
            os.unlink(path)

    def test_custom_query_passes(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE orders (id INTEGER, active INTEGER)"
        )
        conn.executemany(
            "INSERT INTO orders VALUES (?,?)", [(1, 1), (2, 1), (3, 0)]
        )
        conn.commit()
        conn.close()
        try:
            claim = EvidenceClaim(
                kind="row_count",
                description="active orders count",
                db_path=path,
                query="SELECT COUNT(*) FROM orders WHERE active=1",
                min_rows=2,
            )
            result = db_check.check(claim)
            assert result.passed is True
        finally:
            os.unlink(path)

    def test_no_db_path_fails(self):
        claim = EvidenceClaim(
            kind="row_count",
            description="no db path",
            table="items",
            min_rows=1,
        )
        result = db_check.check(claim)
        assert result.passed is False

    def test_no_table_or_query_fails(self):
        path = self._make_db(rows=1)
        try:
            claim = EvidenceClaim(
                kind="row_count",
                description="no table or query",
                db_path=path,
                min_rows=1,
            )
            result = db_check.check(claim)
            assert result.passed is False
        finally:
            os.unlink(path)

    def test_missing_db_file_fails(self):
        claim = EvidenceClaim(
            kind="row_count",
            description="db does not exist",
            db_path="/nonexistent/totally_missing.db",
            table="items",
            min_rows=1,
        )
        result = db_check.check(claim)
        assert result.passed is False


# ─── command_check ────────────────────────────────────────────────────────────

class TestCommandCheck:
    def test_exit_zero_passes(self):
        claim = EvidenceClaim(
            kind="command_exit",
            description="true exits 0",
            command="true",
            expected_exit=0,
        )
        result = command_check.check(claim)
        assert result.passed is True

    def test_exit_nonzero_when_expecting_zero_fails(self):
        claim = EvidenceClaim(
            kind="command_exit",
            description="false exits 1, expecting 0",
            command="false",
            expected_exit=0,
        )
        result = command_check.check(claim)
        assert result.passed is False

    def test_expected_nonzero_exit_passes(self):
        claim = EvidenceClaim(
            kind="command_exit",
            description="false exits 1, expecting 1",
            command="false",
            expected_exit=1,
        )
        result = command_check.check(claim)
        assert result.passed is True

    def test_command_with_output_passes(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        ) as f:
            f.write("content\n")
            path = f.name
        try:
            claim = EvidenceClaim(
                kind="command_exit",
                description="ls the temp file",
                command=f"ls {path}",
                expected_exit=0,
            )
            result = command_check.check(claim)
            assert result.passed is True
        finally:
            os.unlink(path)

    def test_no_command_fails(self):
        claim = EvidenceClaim(
            kind="command_exit", description="missing command field"
        )
        result = command_check.check(claim)
        assert result.passed is False

    def test_default_expected_exit_is_zero(self):
        """When expected_exit is not set, default is 0."""
        claim = EvidenceClaim(
            kind="command_exit",
            description="true with no explicit expected_exit",
            command="true",
        )
        result = command_check.check(claim)
        assert result.passed is True

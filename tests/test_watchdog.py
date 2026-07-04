"""
Tests for Watchdog — heartbeat write, freshness check, stale detection.
"""
import os
import pytest
import tempfile
from datetime import datetime, timezone, timedelta

from attestor.core.watchdog import Watchdog


# ─── Helpers ──────────────────────────────────────────────────────────────────

def temp_heartbeat_path():
    """Return a path to a non-existent temp file (caller manages cleanup)."""
    fd, path = tempfile.mkstemp(suffix=".heartbeat")
    os.close(fd)
    os.unlink(path)
    return path


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestHeartbeat:
    def test_heartbeat_creates_file_with_timestamp(self):
        path = temp_heartbeat_path()
        try:
            watchdog = Watchdog(heartbeat_file=path)
            watchdog.heartbeat()
            assert os.path.exists(path)
            content = open(path).read().strip()
            parsed = datetime.fromisoformat(content)
            assert parsed is not None
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_heartbeat_timestamp_is_recent(self):
        path = temp_heartbeat_path()
        try:
            before = datetime.now(timezone.utc)
            watchdog = Watchdog(heartbeat_file=path)
            watchdog.heartbeat()
            after = datetime.now(timezone.utc)
            last = watchdog.last_run()
            assert last is not None
            assert before <= last <= after
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_heartbeat_overwrites_stale_timestamp(self):
        path = temp_heartbeat_path()
        try:
            stale = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            with open(path, "w") as f:
                f.write(stale)

            watchdog = Watchdog(heartbeat_file=path)
            watchdog.heartbeat()

            last = watchdog.last_run()
            age = datetime.now(timezone.utc) - last
            assert age.total_seconds() < 5  # Updated to now
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestCheck:
    def test_check_returns_true_within_window(self):
        path = temp_heartbeat_path()
        try:
            with open(path, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
            watchdog = Watchdog(heartbeat_file=path, max_age_minutes=60)
            assert watchdog.check() is True
        finally:
            os.unlink(path)

    def test_check_returns_false_when_stale(self):
        path = temp_heartbeat_path()
        try:
            stale_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            with open(path, "w") as f:
                f.write(stale_ts)
            watchdog = Watchdog(heartbeat_file=path, max_age_minutes=60)
            assert watchdog.check() is False
        finally:
            os.unlink(path)

    def test_check_returns_false_when_file_missing(self):
        path = "/tmp/attestor_test_no_such_heartbeat_xyz789abc"
        if os.path.exists(path):
            os.unlink(path)
        watchdog = Watchdog(heartbeat_file=path, max_age_minutes=60)
        assert watchdog.check() is False

    def test_check_exactly_at_threshold_passes(self):
        """A heartbeat written exactly at the threshold boundary is still OK."""
        path = temp_heartbeat_path()
        try:
            # Write timestamp 59 minutes ago — should pass a 60-minute window
            ts = (datetime.now(timezone.utc) - timedelta(minutes=59)).isoformat()
            with open(path, "w") as f:
                f.write(ts)
            watchdog = Watchdog(heartbeat_file=path, max_age_minutes=60)
            assert watchdog.check() is True
        finally:
            os.unlink(path)

    def test_check_just_over_threshold_fails(self):
        """A heartbeat 61 minutes old fails a 60-minute window."""
        path = temp_heartbeat_path()
        try:
            ts = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
            with open(path, "w") as f:
                f.write(ts)
            watchdog = Watchdog(heartbeat_file=path, max_age_minutes=60)
            assert watchdog.check() is False
        finally:
            os.unlink(path)


class TestLastRun:
    def test_last_run_returns_none_when_file_missing(self):
        watchdog = Watchdog(heartbeat_file="/tmp/attestor_no_file_def456")
        assert watchdog.last_run() is None

    def test_last_run_returns_correct_timestamp(self):
        path = temp_heartbeat_path()
        try:
            now = datetime.now(timezone.utc)
            with open(path, "w") as f:
                f.write(now.isoformat())
            watchdog = Watchdog(heartbeat_file=path)
            last = watchdog.last_run()
            assert last is not None
            assert abs((last - now).total_seconds()) < 1
        finally:
            os.unlink(path)

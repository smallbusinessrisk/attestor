"""
attestor.adapters.store.sqlite
------------------------------
SQLite reference implementation of the LedgerAdapter.

This is the reference store — batteries included. For production use,
swap in a Postgres adapter or any other backend that implements LedgerAdapter.

Tables:
    commitments         — the authoritative work ledger
    audit_log           — append-only audit trail
    human_review_queue  — claims awaiting human judgment
    shadow_log          — shadow mode observations (never blocks)
"""
import sqlite3
import json
import os
from typing import Optional
from datetime import datetime, timezone

from attestor.core.ledger import LedgerAdapter, Commitment, now_utc, new_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    maker_id TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','in_progress','completed','failed','overdue')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    verified_at TEXT,
    verified_by TEXT,
    evidence TEXT,
    blocker TEXT,
    due_at TEXT,
    metadata TEXT       -- JSON blob for adapters to store extra state
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS human_review_queue (
    id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL,
    claim_description TEXT NOT NULL,
    agent_output TEXT DEFAULT '',
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','approved','rejected')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shadow_log (
    id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL,
    claim_kind TEXT NOT NULL,
    claim_description TEXT NOT NULL,
    passed INTEGER NOT NULL,        -- 1=pass, 0=fail
    measured_value TEXT,
    expected_value TEXT,
    would_block INTEGER NOT NULL,   -- 1=would have blocked, 0=would have passed
    recorded_at TEXT NOT NULL
);
"""


class SQLiteLedger(LedgerAdapter):
    """
    SQLite-backed commitments ledger.

    Usage:
        ledger = SQLiteLedger("attestor.db")
        # Pass to MakerAPI and CheckerAPI
    """

    def __init__(self, db_path: str = "attestor.db"):
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _row_to_commitment(self, row) -> Commitment:
        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                pass
        return Commitment(
            id=row["id"],
            maker_id=row["maker_id"],
            task=row["task"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            verified_at=row["verified_at"],
            verified_by=row["verified_by"],
            evidence=row["evidence"],
            blocker=row["blocker"],
            due_at=row["due_at"],
            metadata=meta,
        )

    # ─── Core LedgerAdapter methods ───────────────────────────────────────────

    def open(self, maker_id: str, task: str, due_at: Optional[str] = None) -> Commitment:
        cid = new_id()
        ts = now_utc()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO commitments (id, maker_id, task, status, created_at, due_at) VALUES (?,?,?,?,?,?)",
                (cid, maker_id, task, "open", ts, due_at)
            )
            conn.execute(
                "INSERT INTO audit_log (commitment_id, actor_id, action, detail) VALUES (?,?,?,?)",
                (cid, maker_id, "created", task)
            )
        return self.get(cid)

    def start(self, commitment_id: str, maker_id: str) -> Commitment:
        c = self.get(commitment_id)
        if c is None:
            raise ValueError(f"Commitment {commitment_id} not found")
        if c.maker_id != maker_id:
            raise PermissionError(
                f"SoD violation: {maker_id} cannot start commitment owned by {c.maker_id}"
            )
        with self._connect() as conn:
            conn.execute(
                "UPDATE commitments SET status='in_progress', started_at=? WHERE id=?",
                (now_utc(), commitment_id)
            )
            conn.execute(
                "INSERT INTO audit_log (commitment_id, actor_id, action) VALUES (?,?,?)",
                (commitment_id, maker_id, "started")
            )
        return self.get(commitment_id)

    def set_pending_evidence(self, commitment_id: str, evidence_json: str):
        """Store pending evidence claims for the validator to pick up."""
        c = self.get(commitment_id)
        meta = c.metadata or {}
        meta["pending_evidence"] = evidence_json
        with self._connect() as conn:
            conn.execute(
                "UPDATE commitments SET metadata=? WHERE id=?",
                (json.dumps(meta), commitment_id)
            )

    def close(self, commitment_id: str, evidence: str, verified_by: str) -> Commitment:
        ts = now_utc()
        with self._connect() as conn:
            conn.execute(
                "UPDATE commitments SET status='completed', evidence=?, verified_at=?, verified_by=?, completed_at=? WHERE id=?",
                (evidence, ts, verified_by, ts, commitment_id)
            )
            conn.execute(
                "INSERT INTO audit_log (commitment_id, actor_id, action, detail) VALUES (?,?,?,?)",
                (commitment_id, verified_by, "verified", evidence[:200])
            )
        return self.get(commitment_id)

    def fail(self, commitment_id: str, reason: str, rejected_by: str) -> Commitment:
        ts = now_utc()
        with self._connect() as conn:
            conn.execute(
                "UPDATE commitments SET status='failed', blocker=?, completed_at=?, verified_by=? WHERE id=?",
                (reason, ts, rejected_by, commitment_id)
            )
            conn.execute(
                "INSERT INTO audit_log (commitment_id, actor_id, action, detail) VALUES (?,?,?,?)",
                (commitment_id, rejected_by, "rejected", reason[:200])
            )
        return self.get(commitment_id)

    def get(self, commitment_id: str) -> Optional[Commitment]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM commitments WHERE id=?", (commitment_id,)).fetchone()
        return self._row_to_commitment(row) if row else None

    def list(self, status: Optional[str] = None, maker_id: Optional[str] = None) -> list:
        sql = "SELECT * FROM commitments WHERE 1=1"
        params = []
        if status:
            sql += " AND status=?"; params.append(status)
        if maker_id:
            sql += " AND maker_id=?"; params.append(maker_id)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_commitment(r) for r in rows]

    def flag_overdue(self) -> list:
        ts = now_utc()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM commitments WHERE status IN ('open','in_progress') AND due_at IS NOT NULL AND due_at < ?",
                (ts,)
            ).fetchall()
            for row in rows:
                conn.execute("UPDATE commitments SET status='overdue' WHERE id=?", (row["id"],))
                conn.execute(
                    "INSERT INTO audit_log (commitment_id, actor_id, action) VALUES (?,?,?)",
                    (row["id"], "watchdog", "flagged_overdue")
                )
        return [self._row_to_commitment(r) for r in rows]

    # ─── Human review queue methods ───────────────────────────────────────────

    def _row_to_review_item(self, row):
        from attestor.core.queue import HumanReviewItem
        return HumanReviewItem(
            id=row["id"],
            commitment_id=row["commitment_id"],
            claim_description=row["claim_description"],
            agent_output=row["agent_output"] or "",
            status=row["status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            created_at=row["created_at"],
        )

    def enqueue_review(self, item_id: str, commitment_id: str,
                       claim_description: str, agent_output: str,
                       created_at: str) -> None:
        """Insert a new pending human review item."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO human_review_queue
                   (id, commitment_id, claim_description, agent_output, status, created_at)
                   VALUES (?,?,?,?,'pending',?)""",
                (item_id, commitment_id, claim_description, agent_output, created_at)
            )

    def list_pending_reviews(self, commitment_id: Optional[str] = None) -> list:
        """Return pending human review items, optionally filtered by commitment."""
        sql = "SELECT * FROM human_review_queue WHERE status='pending'"
        params = []
        if commitment_id is not None:
            sql += " AND commitment_id=?"
            params.append(commitment_id)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_review_item(r) for r in rows]

    def get_review(self, item_id: str):
        """Retrieve a single review item by ID (any status)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM human_review_queue WHERE id=?", (item_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Review item {item_id} not found")
        return self._row_to_review_item(row)

    def resolve_review(self, item_id: str, approved: bool,
                       reviewed_by: str, reviewed_at: str) -> None:
        """Mark a review item approved or rejected."""
        status = "approved" if approved else "rejected"
        with self._connect() as conn:
            conn.execute(
                """UPDATE human_review_queue
                   SET status=?, reviewed_by=?, reviewed_at=?
                   WHERE id=?""",
                (status, reviewed_by, reviewed_at, item_id)
            )

    # ─── Shadow log methods ───────────────────────────────────────────────────

    def log_shadow(self, entry_id: str, commitment_id: str, claim_kind: str,
                   claim_description: str, passed: bool, measured_value: str,
                   expected_value: str, would_block: bool,
                   recorded_at: str) -> None:
        """Insert a shadow log entry."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO shadow_log
                   (id, commitment_id, claim_kind, claim_description,
                    passed, measured_value, expected_value, would_block, recorded_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id, commitment_id, claim_kind, claim_description,
                    1 if passed else 0,
                    measured_value, expected_value,
                    1 if would_block else 0,
                    recorded_at,
                )
            )

    def shadow_summary(self) -> dict:
        """Aggregate shadow_log into discrepancy statistics."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0]
            passed = conn.execute(
                "SELECT COUNT(*) FROM shadow_log WHERE passed=1"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM shadow_log WHERE passed=0"
            ).fetchone()[0]

            by_kind_rows = conn.execute(
                """SELECT claim_kind,
                          COUNT(*) AS total,
                          SUM(CASE WHEN passed=0 THEN 1 ELSE 0 END) AS would_fail
                   FROM shadow_log
                   GROUP BY claim_kind
                   ORDER BY claim_kind"""
            ).fetchall()

        by_kind = {}
        for row in by_kind_rows:
            by_kind[row["claim_kind"]] = {
                "measured": row["total"],
                "would_have_failed": row["would_fail"],
            }

        discrepancy_rate = round(failed / total, 4) if total > 0 else 0.0

        return {
            "total_measured": total,
            "would_have_passed": passed,
            "would_have_failed": failed,
            "discrepancy_rate": discrepancy_rate,
            "by_kind": by_kind,
        }

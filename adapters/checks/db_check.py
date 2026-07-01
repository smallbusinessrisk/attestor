"""SQLite row count check — queries the actual database."""
import sqlite3
from attestor.core.evidence import EvidenceClaim, EvidenceResult

def check(claim: EvidenceClaim) -> EvidenceResult:
    db_path = claim.db_path
    if not db_path:
        return EvidenceResult(claim=claim, passed=False, measured="no db_path", expected="db_path required")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        if claim.query:
            row = conn.execute(claim.query).fetchone()
            actual = row[0] if row else 0
        elif claim.table:
            row = conn.execute(f"SELECT COUNT(*) FROM {claim.table}").fetchone()
            actual = row[0] if row else 0
        else:
            return EvidenceResult(claim=claim, passed=False,
                                  measured="no table or query", expected="table or query required")
        conn.close()
    except Exception as e:
        return EvidenceResult(claim=claim, passed=False,
                              measured=f"error: {e}", expected=f">= {claim.min_rows or 1} rows")
    min_rows = claim.min_rows or 1
    passed = actual >= min_rows
    return EvidenceResult(claim=claim, passed=passed,
                          measured=f"{actual} rows",
                          expected=f">= {min_rows} rows")

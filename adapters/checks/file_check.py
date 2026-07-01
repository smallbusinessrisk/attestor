"""File existence and size check."""
import os
from attestor.core.evidence import EvidenceClaim, EvidenceResult

def check(claim: EvidenceClaim) -> EvidenceResult:
    path = claim.path
    if not path:
        return EvidenceResult(claim=claim, passed=False, measured="no path", expected="path required")
    if not os.path.exists(path):
        return EvidenceResult(claim=claim, passed=False,
                              measured=f"file not found: {path}",
                              expected=f"file exists at {path}")
    size = os.path.getsize(path)
    min_bytes = claim.min_bytes or 0
    passed = size >= min_bytes
    return EvidenceResult(claim=claim, passed=passed,
                          measured=f"{path} exists ({size} bytes)",
                          expected=f"exists, >= {min_bytes} bytes")

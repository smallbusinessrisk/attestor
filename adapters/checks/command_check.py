"""Command exit code check."""
import subprocess
from attestor.core.evidence import EvidenceClaim, EvidenceResult

def check(claim: EvidenceClaim) -> EvidenceResult:
    if not claim.command:
        return EvidenceResult(claim=claim, passed=False, measured="no command", expected="command required")
    expected_exit = claim.expected_exit if claim.expected_exit is not None else 0
    try:
        result = subprocess.run(claim.command, shell=True, capture_output=True, timeout=30)
        actual = result.returncode
    except Exception as e:
        return EvidenceResult(claim=claim, passed=False,
                              measured=f"error: {e}", expected=f"exit {expected_exit}")
    passed = actual == expected_exit
    return EvidenceResult(claim=claim, passed=passed,
                          measured=f"exit {actual}",
                          expected=f"exit {expected_exit}",
                          detail=result.stderr.decode()[:200] if not passed else None)

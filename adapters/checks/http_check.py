"""HTTP status code check — hits the real endpoint, never trusts pasted output."""
import urllib.request
import urllib.error
from attestor.core.evidence import EvidenceClaim, EvidenceResult

def check(claim: EvidenceClaim) -> EvidenceResult:
    url = claim.url
    expected = claim.expected_status or 200
    if not url:
        return EvidenceResult(claim=claim, passed=False, measured="no url", expected="url required")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            actual = resp.status
    except urllib.error.HTTPError as e:
        actual = e.code
    except Exception as e:
        return EvidenceResult(claim=claim, passed=False,
                              measured=f"error: {e}", expected=f"HTTP {expected}")
    passed = actual == expected
    return EvidenceResult(claim=claim, passed=passed,
                          measured=f"HTTP {actual}",
                          expected=f"HTTP {expected}")

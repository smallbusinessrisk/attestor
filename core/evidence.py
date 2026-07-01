"""
attestor.core.evidence
----------------------
The evidence contract.

Evidence is not free-form text. It is a structured claim that the independent
validator can re-measure. Claimed evidence and verified evidence are separately
sourced — only the validator's independent measurement counts.

A fabricating agent can paste a plausible '200 OK' as easily as it can fabricate
the work. So the validator never reads the agent's transcript. It measures the world.
"""
from dataclasses import dataclass
from typing import Optional, Literal


EvidenceKind = Literal["file_exists", "http_status", "row_count", "command_exit", "custom"]


@dataclass
class EvidenceClaim:
    """
    A single verifiable claim submitted by the maker as evidence of completion.

    The validator re-measures this independently. If the measured result matches
    the claimed result, the commitment passes. If not, VALIDATOR FAIL is written.
    """
    kind: EvidenceKind
    description: str            # Human-readable label

    # file_exists
    path: Optional[str] = None
    min_bytes: Optional[int] = None

    # http_status
    url: Optional[str] = None
    expected_status: Optional[int] = None

    # row_count
    db_path: Optional[str] = None
    table: Optional[str] = None
    min_rows: Optional[int] = None
    query: Optional[str] = None     # Override: custom SQL returning a count

    # command_exit
    command: Optional[str] = None
    expected_exit: Optional[int] = None   # default 0

    # custom
    custom_fn: Optional[str] = None       # dotted import path to a callable


@dataclass
class EvidenceResult:
    """The result of the validator independently measuring an EvidenceClaim."""
    claim: EvidenceClaim
    passed: bool
    measured: str       # What the validator actually observed
    expected: str       # What the maker claimed
    detail: Optional[str] = None


def format_fail(results: list[EvidenceResult]) -> str:
    """Format a VALIDATOR FAIL message from failed evidence results."""
    lines = ["VALIDATOR FAIL:"]
    for r in results:
        if not r.passed:
            lines.append(f"  [{r.claim.kind}] {r.claim.description}")
            lines.append(f"    Expected: {r.expected}")
            lines.append(f"    Measured: {r.measured}")
            if r.detail:
                lines.append(f"    Detail:   {r.detail}")
    return "\n".join(lines)

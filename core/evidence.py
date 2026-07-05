"""
attestor.core.evidence
----------------------
Evidence contract.

Evidence is not free-form text. Each claim is a structured, independently
verifiable statement. Only the validator's independent measurement counts —
fabricating '200 OK' is easy, so the validator never reads the maker's
transcript. It measures the world directly.
"""
from dataclasses import dataclass
from typing import Optional, Literal

EvidenceKind = Literal[
    "file_exists",
    "http_status",
    "row_count",
    "command_exit",
    "git_commit",
    "human_review",
    "custom",
]


@dataclass
class EvidenceClaim:
    """
    A single verifiable claim submitted by the maker as evidence of completion.

    The validator re-measures independently. If the measured result matches the
    claimed result, the commitment passes. If not, VALIDATOR FAIL is written.
    """
    kind: EvidenceKind
    description: str                  # Human-readable label

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
    query: Optional[str] = None       # Override: custom SQL returning count

    # command_exit
    command: Optional[str] = None
    expected_exit: Optional[int] = None   # default 0

    # git_commit
    repo_path: Optional[str] = None
    commit_hash: Optional[str] = None

    # custom
    custom_fn: Optional[str] = None   # dotted path to callable

    # human_review — non-binary claims that require human judgment
    requires_human_review: bool = False
    agent_output: str = ""            # What the agent submitted for this claim


@dataclass
class EvidenceResult:
    """The result of the validator independently measuring an EvidenceClaim."""
    claim: EvidenceClaim
    passed: bool
    measured: str       # What the validator actually observed
    expected: str       # What the claim required
    detail: Optional[str] = None


def format_fail(results: list) -> str:
    """Format a VALIDATOR FAIL message for failed evidence results."""
    lines = ["VALIDATOR FAIL:"]
    for r in results:
        if not r.passed:
            lines.append(f"  [{r.claim.kind}] {r.claim.description}")
            lines.append(f"    Expected: {r.expected}")
            lines.append(f"    Measured: {r.measured}")
            if r.detail:
                lines.append(f"    Detail:   {r.detail}")
    return "\n".join(lines)

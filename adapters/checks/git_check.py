"""
Git commit existence check.

Independently verifies that a specific commit hash exists in a git repo's
history using `git cat-file -t`. Returns a commit object type confirmation.
Never trusts the maker's pasted output — queries git directly.
"""
import subprocess
import re
from attestor.core.evidence import EvidenceClaim, EvidenceResult


# Minimum 4 chars (git abbreviates to 4+ for short hashes), max 40 for full SHA-1
_HASH_RE = re.compile(r'^[0-9a-fA-F]{4,40}$')


def check(claim: EvidenceClaim) -> EvidenceResult:
    """
    Verify that a specific commit hash exists in the given repo's git history.

    Uses `git -C <repo_path> cat-file -t <commit_hash>` which returns "commit"
    for a valid commit object, or exits non-zero if the object is missing.

    Handles: repo not found, git not installed, hash not found, invalid format.
    """
    repo_path = claim.repo_path
    commit_hash = claim.commit_hash

    if not repo_path:
        return EvidenceResult(
            claim=claim, passed=False,
            measured="no repo_path provided",
            expected="repo_path required",
        )

    if not commit_hash:
        return EvidenceResult(
            claim=claim, passed=False,
            measured="no commit_hash provided",
            expected="commit_hash required",
        )

    # Validate hash format before calling git — catches junk early
    if not _HASH_RE.match(commit_hash):
        return EvidenceResult(
            claim=claim, passed=False,
            measured=f"invalid hash format: {commit_hash!r}",
            expected="valid hex git commit hash (4–40 characters)",
        )

    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, "cat-file", "-t", commit_hash],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return EvidenceResult(
            claim=claim, passed=False,
            measured="git not found in PATH",
            expected="git available in PATH",
        )
    except subprocess.TimeoutExpired:
        return EvidenceResult(
            claim=claim, passed=False,
            measured="git command timed out after 10s",
            expected=f"commit {commit_hash} verified within timeout",
        )
    except Exception as e:
        return EvidenceResult(
            claim=claim, passed=False,
            measured=f"subprocess error: {e}",
            expected=f"commit {commit_hash} exists in {repo_path}",
        )

    if proc.returncode != 0:
        stderr = proc.stderr.strip().lower()
        if "not a git repository" in stderr:
            return EvidenceResult(
                claim=claim, passed=False,
                measured=f"not a git repository: {repo_path}",
                expected=f"git repository at {repo_path}",
                detail=proc.stderr.strip(),
            )
        return EvidenceResult(
            claim=claim, passed=False,
            measured=f"commit not found: {commit_hash}",
            expected=f"commit {commit_hash} in {repo_path}",
            detail=proc.stderr.strip() or None,
        )

    obj_type = proc.stdout.strip()
    if obj_type == "commit":
        return EvidenceResult(
            claim=claim, passed=True,
            measured=f"commit {commit_hash} verified (type=commit)",
            expected=f"commit {commit_hash} in {repo_path}",
        )
    # Object exists but is not a commit (blob, tree, tag, etc.)
    return EvidenceResult(
        claim=claim, passed=False,
        measured=f"{commit_hash} is a {obj_type!r}, not a commit",
        expected=f"commit object at {commit_hash}",
    )

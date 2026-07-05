"""
Attestor — Accountability and verification layer for AI agent fleets.

So that "done" means proven, not claimed.

Quick start
-----------
    from attestor import MakerAPI, CheckerAPI, Watchdog, EvidenceClaim, SQLiteLedger
    import os

    ledger = SQLiteLedger("attestor.db")
    maker  = MakerAPI(ledger=ledger, maker_id="my-agent")

    # 1. Log a commitment BEFORE doing any work
    c = maker.commit("Deploy the feature", due_hours=2)
    maker.start(c.id)

    # 2. Do the actual work …

    # 3. Submit structured evidence for the validator to re-measure
    maker.submit_evidence(c.id, [
        EvidenceClaim(
            kind="http_status",
            description="/health returns 200",
            url="http://localhost:8080/health",
            expected_status=200,
        ),
    ])

    # 4. In the validator process (has ATTESTOR_VERIFIER_TOKEN, never the maker):
    token   = os.environ["ATTESTOR_VERIFIER_TOKEN"]
    checker = CheckerAPI(ledger=ledger, verifier_id="validator", token=token)
    summary = checker.run()   # independently re-measures each claim

Maker-checker principle
-----------------------
The agent that does the work can never be the one that verifies it.
ATTESTOR_VERIFIER_TOKEN must only be present in the validator process.
CheckerAPI refuses instantiation without it — SoD is enforced at the
permission layer, not the prompt.
"""

import os as _os

# ─── Path bootstrap ───────────────────────────────────────────────────────────
# attestor uses a namespace-package layout where core/ and adapters/ live at
# the repo root (same level as this attestor/ package dir).
#
# When Python finds this __init__.py from the repo root in sys.path (the usual
# case when running pytest or scripts directly), attestor.core.* and
# attestor.adapters.* would otherwise fail because they are not subdirectories
# of attestor/.
#
# Extending __path__ to include the repo root teaches Python to look there for
# attestor.core and attestor.adapters — no sys.path surgery needed.
_repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo_root not in __path__:
    __path__.append(_repo_root)

del _os, _repo_root

# ─── Public API ───────────────────────────────────────────────────────────────

__version__ = "0.6.0"

from attestor.core.maker import MakerAPI
from attestor.core.checker import CheckerAPI, SoDViolation
from attestor.core.watchdog import Watchdog
from attestor.core.evidence import EvidenceClaim, EvidenceResult, EvidenceKind
from attestor.core.queue import HumanCheckerQueue, HumanReviewItem
from attestor.core.shadow import ShadowLogger
from attestor.adapters.store.sqlite import SQLiteLedger

__all__ = [
    # Core APIs
    "MakerAPI",
    "CheckerAPI",
    "SoDViolation",
    "Watchdog",
    # Evidence types
    "EvidenceClaim",
    "EvidenceResult",
    "EvidenceKind",
    # Human review queue
    "HumanCheckerQueue",
    "HumanReviewItem",
    # Shadow mode
    "ShadowLogger",
    # Reference store
    "SQLiteLedger",
    # Metadata
    "__version__",
]

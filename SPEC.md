# Attestor — Project Spec & Go/No-Go

*Purpose: the design doc behind the reference implementation.*

---

## Thesis

Extract Layers 2–3 of the Trust Stack (accountability + independent verification), add the maker-checker gate and enforced segregation of duties, and generalize them into a runtime-agnostic enforcement layer any agent system can wrap.

---

## Minimal extractable core

1. **Commitments store** — schema with: id, maker_id, task, status, created_at, evidence, verified_at, blocker.
2. **Pre-work logging** — commit() opens a commitment before work begins; no open commitment = not started.
3. **Evidence contract** — structured claim shape (path / url+status / table+rows / command+exit).
4. **Independent validator** — re-measurement runner that independently checks reality, not the agent's transcript.
5. **Maker-checker gate** — the identity closing a commitment ≠ the identity that opened it. Enforced by ATTESTOR_VERIFIER_TOKEN.
6. **SoD boundary** — makers cannot write to the ledger verdict. Enforced at the API/permission layer.
7. **Validator dead-man's switch** — heartbeat + alert if the validator misses its window.

Items 1–6 are the minimum for the pattern to be real. Item 7 is what makes it trustworthy in production.

---

## Ship vs. stays-private

| Layer | Disposition | Why |
|-------|-------------|-----|
| L2 Accountability | **Ship (core)** | The contribution. Generalized off production specifics. |
| L3 Verification | **Ship (core)** | The contribution. This is the re-measurement validator. |
| Maker-checker + SoD | **Ship (core)** | The differentiator; nobody else names these. |
| L4 Task routing | **Example only** | Minimal kanban concept; router is optional glue. |
| L5 Named agent fleet | **Example only** | Ship the concept (named identities accrue track records). |
| L1 Memory | **Private** | Environment-specific; overlaps managed runtime features. |
| L6 Cost / model routing | **Private** | Tied to specific Ollama/proxy setup. |
| L7 Infrastructure | **Private** | systemd/UFW/backups are ops, not a reusable pattern. |
| L8 Dashboard | **Private** | Screenshot in README at most. |

---

## Differentiation

| | Attestor | Agentic OS | MS Agent Governance Toolkit |
|--|---------|-----------|---------------------------|
| Target | Persistent **business-ops** fleets | Coding agents | Enterprise agents |
| Deploy | Self-hosted, small | git hooks / CI | Azure / K8s |
| Distinctive primitive | **Maker-checker + SoD** | Phase/evidence CI gates | Policy engine + compliance |
| Lens | Financial-controls discipline | SDLC governance | Enterprise risk / regulatory |

---

## Adapter interface

Three abstractions, three reference implementations:

- **Store adapter** — `LedgerAdapter` interface (open, start, close, fail, get, list). Reference: SQLite.
- **Notifier adapter** — `alert(message)`. Reference: stdout. Example: Discord webhook.
- **Check adapters** — `check(claim) → EvidenceResult`. Reference: file_exists, http_status, row_count, command_exit.

Core depends only on the interfaces. No runtime, chat platform, or model provider in the core.

---

## Go / No-Go

**Go if** the goal is a credibility artifact for Small Business Risk Inc. Low bar, high payoff, nil maintenance.

**Reconsider if** the goal is adoption/stars as an end in itself — a larger, different commitment.

**Do not ship** the full production harness. It reads as a personal rig and undercuts the credibility goal.

# Paradox architecture

Paradox maps onto the problem statement's reference architecture one-to-one. Its core idea differs from it in one place: findings come from **business invariants checked on a shadow ledger**, not from payload signatures.

```mermaid
flowchart LR
  subgraph Triggers
    D[CI/CD deploy webhook]
    B[JS bundle diff watcher]
    M[Manual / schedule]
  end
  subgraph Learn["Recon agent + app knowledge model"]
    R1[Bundle parser<br/>routes + body shapes]
    R2[HAR learner<br/>journeys, data-flow refs,<br/>roles, auth scheme, enums,<br/>masking, one-time values]
    R3[Log analyser<br/>90-day hits, last seen]
    R4[Bounded prober<br/>/v1 /v2, /internal, /debug]
    L[Ledger calibration<br/>by experiment]
  end
  subgraph Inventory["Inventory agent"]
    I1[active / zombie / shadow /<br/>retired / new]
    I2[Generated OpenAPI 3]
  end
  subgraph Hunt["Planner + executors"]
    P[Experiment planner<br/>changed routes first]
    O[Mutation operators<br/>repeat, skip, graft, tamper,<br/>mass-assign, quantity, swap tenant,<br/>drop session, lower role, SQLi, malformed]
    X[Journey runner<br/>canaries + shadow ledger]
  end
  subgraph Judge["Verifier, triage, reporter, retest"]
    V[12 invariant oracles]
    V2[Reproduce 2 more times<br/>from fresh objects]
    V3[Delta-debug to<br/>minimal proof]
    T[Severity in INR + context,<br/>owner, fix, curl, ticket]
    RT[Retest every deploy,<br/>auto-close, reopen regressions]
  end
  S[[Safety gate<br/>allowlist · own-object rule · rate cap ·<br/>health back-off · kill switch · audit log]]
  H[[Human queue<br/>policy questions]]
  D & B & M --> R1 & R2 & R3 & R4
  R1 & R2 & R3 & R4 --> I1 --> I2
  R2 --> L --> P
  I1 --> P --> O --> X --> V --> V2 --> V3 --> T --> RT
  V -.ambiguous.-> H
  X <--> S
```

## Components

| Reference component (problem statement) | Paradox module | Notes |
|---|---|---|
| Change triggers | `server.py` (`/hooks/deploy`, bundle watcher), `engine.learn()` diff | New or changed route signatures become the focus set; experiments touching them run first. |
| Recon agent + knowledge graph | `recon.py`, `runner.Semantics` | Routes from the bundle; journeys from HAR with **data-flow references** (which response value feeds which later request); object types, observer, settle and release actions; lifecycle enum; masking policy; one-time values; auth scheme. |
| Inventory agent | `recon.probe`, `recon.classify`, `recon.openapi` | Probing is bounded (version neighbours plus ~90 internal/debug paths). "Route exists" is decided by comparing to the fingerprint of a random non-existent route. |
| Attack planner | `hunt.Hunter.plan` | Operators are applied to learned journeys, never sprayed. Deduplicated by (operator, endpoint, field, context). |
| Specialist executors | `hunt.Hunter.execute`, `runner.Runner.run` | One runner, many operators. Every run plants canaries and snapshots wallets. |
| Safety layer | `safety.Gate` | Enforced in code. The own-object rule means state-changing calls may only address object ids Paradox created. |
| Verifier | `hunt.verify`, `hunt.minimise` | 3/3 reproduction from fresh objects, then delta-debugging. |
| Triage + reporter | `triage.py` | Severity from the invariant, measured INR, data class (PII), reachability, and zombie/shadow status. Owner comes from asset-ownership data. |
| Retest | `engine.retest` | Runs every cycle. A proof that no longer reproduces twice closes the ticket. A closed finding that comes back is reopened as a regression. |
| Human reviewer | `hunt._add_review`, dashboard queue | Policy-dependent observations (e.g. a lower role can *read* something) are never auto-filed. Accounts flagged `requires_approval` are never used autonomously. |

## The invariants

| Invariant | How it is measured | Typical bugs it catches |
|---|---|---|
| `money_created` | Wallet after > wallet before, for one agency's own sequence | Double refund, refund of an unpaid hold, refund on pre-discount gross, negative quantity |
| `underpayment` | Same final object state as the untouched journey, but less money moved | Client-set price or fare, status set to confirmed without payment |
| `cross_tenant_read` | Agency A's canary (or object id plus tenant id) appears in agency B's response | IDOR / BOLA on bookings, invoices, legacy routes |
| `cross_tenant_write` | Agency B's action changes agency A's object state or wallet | Cancel or modify another agency's booking |
| `unauthenticated_access` | Canary or object id served with no session | Vouchers, e-tickets |
| `privilege_escalation` | An action seen only from a higher role succeeds from a lower role and changes state | Sub-agent changes markup or limits |
| `mass_assignment` | Client-supplied role / tenant field is reflected | Self-promotion to admin |
| `one_time_reuse` | A value the platform rejected on reuse in recorded traffic is accepted twice | Coupon or promo reuse |
| `invalid_quantity` | Zero or negative quantity accepted and priced at or below zero | Negative rooms or seats |
| `pii_exposure` | A planted passport appears in clear where the platform masks it elsewhere | List endpoints, legacy routes |
| `secret_exposure` | Secret / credential / stack-trace patterns in any response | Debug routes, verbose error handler |
| `sql_injection` | A boolean TRUE condition grows the result set and FALSE shrinks it | Filter concatenation |

## Why there is no LLM in the decision path

The judging rewards precision (20%) and safety (20%). Every Paradox finding is a deterministic, replayable proof, so there is nothing to hallucinate and nothing to tune. An LLM can be added at the edges, for example to label opaque field names or to write narrative ticket text. Those uses are optional plug-ins and never decide whether something is a finding.

## Extending

- **New invariant:** add an oracle in `Hunter._evaluate` and a severity/fix entry in `triage.py`.
- **New operator:** add it in `Hunter.plan`; the runner already supports per-step actor, skip, repeat, field override, query override and raw body.
- **New target:** provide `inputs/` (scope, accounts with tenant/role/privilege, HAR, access logs, ownership). No code changes. The SkyLane holdout proves this.

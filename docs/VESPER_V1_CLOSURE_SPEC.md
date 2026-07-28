# VESPER V1 CLOSURE SPECIFICATION

Status: Director closure specification  
Baseline repository: `goonbam0306/vesper`  
Baseline branch: `main`  
Baseline commit: `5604d8b9b706ca28a64321fd933372bc8c46d18e`  
Purpose: Close the remaining implementation gaps between the current Vesper repository and a defensible Vesper v1 seal.

---

## 0. Authority and Use

This document is the implementation authority for remaining Vesper v1 closure work after the Phase 7–14 conformance pass.

It does **not** replace Vesper's Core Invariants or the authoritative architecture documents. When this document conflicts with a Core Invariant, the Core Invariant wins and the work must stop for Director review.

Use this document to answer:

- what remaining work is still required,
- which existing implementations must be preserved,
- which current "IMPLEMENTED" labels are only partial evidence,
- what must become durable or runtime-integrated,
- what is blocked on Director policy or external credentials,
- what evidence is required before Vesper v1 may be sealed.

The implementation agent must inspect the actual repository before editing.  
A prior checklist label is evidence, not authority.

---

# 1. Non-Negotiable Core Invariants

The following remain binding:

1. Vesper is local-first.
2. The Kernel is the deterministic central authority.
3. The Director retains final authority.
4. LLMs are replaceable cognition, not durable state or authority.
5. Vesper owns memory, process state, permissions, scheduling, model selection, context assembly, actions, persistence, and recovery.
6. Context is a cache, not canonical knowledge.
7. Models receive the smallest solvable world.
8. Deterministic software owns exact operations.
9. Models propose cognition and actions; the Kernel validates and executes.
10. External systems are adapters/devices, not Vesper's memory authority.
11. Every meaningful operation is represented as a Process.
12. Vesperest is the Functional Execution Layer, not a persistent agent persona.
13. Lane and Model Runtime remain orthogonal.
14. Process Policy controls duration/autonomy; it does not define Lane identity.
15. Lane outputs are typed artifacts or typed control outcomes, not persisted hidden chain-of-thought.
16. Fallback repetition never automatically grants a new Lane.
17. New durable Lane activation requires Director approval.
18. A Lane cannot expand its own permission ceiling.
19. Approval and effect execution remain separate.
20. No conformance label may replace executable repository evidence.

---

# 2. Baseline: Preserve, Do Not Rebuild Without Evidence

The baseline repository already contains substantial implementation. Do not redo or replace these systems unless repository evidence shows a concrete defect or a closure task below requires integration changes.

## 2.1 FEL / Lane foundation

Preserve:

- `LaneDefinition`
- versioned `LaneRegistry`
- core Lane catalog: Explore, Analyze, Plan, Code, Diagnose, Verify, Compose
- LaneInvocation lifecycle
- adaptive Lane outcomes
- typed artifacts
- model route selection/escalation foundation
- routing proposal / dispatcher foundation

## 2.2 Dynamic execution

Preserve:

- durable ExecutionGraph
- graph nodes and edges
- retries
- parallel-ready semantics
- waits
- deterministic operation nodes
- graph expansion
- graph revision/replan
- restart recovery primitives
- stalled-cycle detection

## 2.3 Kernel-controlled coding effect

Preserve:

- PatchSet representation
- approval-gated bounded repository application
- repository containment checks
- stale-content validation
- deterministic verification
- composition after PASS
- canonical coding vertical tests

Do not describe current multi-file `os.replace` application as a fully transactional multi-file commit unless that property is explicitly implemented and proven.

## 2.4 Memory and context

Preserve:

- versioned MemoryObjects
- retrieval status
- L2 working set
- ContextPack
- process/lane/artifact/work-unit aware retrieval
- bounded context admission
- memory relations
- compression
- archive
- stale/conflict handling

## 2.5 Product shell / local UI

Preserve current local product surfaces:

- Home
- Conversation
- Projects
- Tasks
- Calendar
- Ideas
- Processes
- Observability
- Memory
- Approvals
- Connections
- Settings
- Lane management

Preserve current Playwright/browser evidence where still valid.

## 2.6 Audit, backup, and local safety

Preserve:

- event journal
- process/effect/approval audit state
- diagnostic export
- backup/restore
- corruption checks
- secret-reference boundary
- secret rotation
- safe artifact export
- loopback/local network boundary

---

# 3. Closure Track A — Persistent Process Runtime Integration

The current repository has Process Policy primitives, recurrence, monitoring, budget objects, pause/resume, timers, and recovery helpers. V1 closure requires these to behave as one durable runtime rather than isolated helper classes.

## A-01 Durable Process Runtime State

### Goal

Runtime state that affects future autonomous behavior must survive restart when that behavior is intended to be persistent.

### Required work

Inspect and classify:

- ProcessBudget
- ProcessMonitor
- recurrence counters
- timer claims
- wake state
- retry/replan/lane invocation budgets
- persistent/monitoring Process continuation metadata

For every stateful field, decide deterministically:

- durable canonical state,
- reconstructable cache,
- intentionally ephemeral state.

Persist all state required for correct post-restart behavior.

### Prohibited shortcut

Do not satisfy this task by only storing the Process Policy configuration while leaving consumed runtime counters or monitor progress in Python memory if that loses required semantics after restart.

### Gate

A persistent or monitoring Process must:

1. consume part of its runtime budget,
2. advance recurrence/monitor state,
3. stop the runtime,
4. restart Vesper,
5. recover the Process without resetting consumed canonical state,
6. continue within the same configured limits.

---

## A-02 Kernel Scheduler Integration

### Goal

Timers, recurrence, monitoring, and Process Policy must feed the actual Kernel scheduling/lifecycle path.

### Required behavior

The normal runtime must be able to:

- detect due timers,
- claim wake work deterministically,
- enqueue or resume eligible Processes,
- enforce recurrence run limits,
- enforce monitor cadence/check limits,
- enforce graph/retry/replan/lane invocation budgets,
- respect approval boundaries,
- avoid double-claim/double-run after restart.

### Gate

No direct test-only call to `ProcessRecurrenceStore.next_run()` or an equivalent helper may be the sole proof of recurring execution.

A gate must show:

```text
durable policy
→ due condition
→ Kernel-owned scheduling decision
→ Process transition
→ FEL execution boundary
→ durable updated policy/runtime state
```

---

## A-03 Startup Reconciliation

### Goal

`Runtime.start()` must perform the complete safe startup reconciliation required for V1.

### Required reconciliation

At minimum inspect and reconcile:

- terminal intents already durably recorded,
- RUNNING Processes without a final result,
- RUNNING graph nodes,
- durable waits,
- timer claims,
- recurring Processes,
- monitoring Processes,
- pending approvals/effects where reconciliation is safe,
- Process Policy runtime state.

### Rule

Recovery must never convert uncertainty into false completion.

Safe default for ambiguous in-flight work is PAUSED/WAITING/retryable state with auditable evidence.

### Gate

A single restart-conformance test must crash or stop the runtime at multiple points and prove deterministic recovery without duplicate external effect or false Process completion.

---

# 4. Closure Track B — Fallback and Reusable Abstraction Evolution

The current fallback implementation is a useful structural proof of concept. V1 closure requires the evolution path to become durable, evidence-based, and capable of distinguishing Skill reuse from a genuinely new Lane boundary.

## B-01 Durable FallbackExecutionRecord

Create a durable fallback execution record owned by Vesper.

Minimum fields should include:

- fallback_execution_id
- process_id
- work_unit_id or graph node reference
- timestamp
- inferred function label
- domain/context tags
- cognitive operations
- normalized input shape
- normalized output shape
- normalized context shape
- tool profile
- evaluation dimensions
- permission shape
- selected model route
- attempt count
- success/failure disposition
- verification result reference
- latency/cost evidence when available
- artifact references
- semantic representation metadata when enabled

Do not store hidden model chain-of-thought.

### Gate

Fallback history survives restart and can be queried by structural and operational features.

---

## B-02 Rich Fallback Fingerprint

Extend matching beyond the current small structural Jaccard proof of concept.

Candidate similarity should be able to consider:

- structural similarity
- semantic similarity
- operational/tool similarity
- permission/effect shape
- evaluation contract similarity
- success/failure history
- recurrence/frequency

Semantic embeddings may assist but must not be the authority.

### Gate

The same functional pattern expressed with different wording, different labels, or different supported language must cluster when operational structure is equivalent, while structurally distinct cognition must remain separate.

---

## B-03 Skill vs Lane Recommendation

The abstraction recommender must no longer effectively hard-code `SKILL`.

Implement evidence-based recommendation among at least:

- reuse existing Lane with different context/Skill,
- create/update Skill,
- propose new Lane,
- insufficient evidence / continue observing.

### Lane recommendation criteria

A new Lane is justified only when the execution boundary materially differs in one or more of:

- tool profile
- context admission
- output artifact contract
- evaluation contract
- permission boundary
- stop/outcome semantics
- capability requirements

A domain-only difference is not sufficient.

### Gate

Tests must include:

1. paraphrased/domain-specific fallback → existing Lane + Skill,
2. structurally new bounded cognition → new Lane candidate,
3. weak/noisy evidence → no promotion proposal.

---

## B-04 Durable Candidate Review and Approval

Candidate review/approval is Director authority and must not be process-memory-only.

Replace or wrap any in-memory-only CandidateReviewStore with durable Kernel-owned state.

Persist:

- candidate identity
- evidence references
- reviewer
- decision
- note
- immutable approval receipt
- decision timestamp
- activation state
- activation receipt
- retirement/supersession lineage where applicable

### Gate

Submit candidate → approve → restart runtime → review and approval still exist → activation requires the same valid durable approval.

---

## B-05 Safe Activation

Activation must not mutate Lane registry silently.

Required path:

```text
Candidate
→ Director review
→ approval receipt
→ deterministic activation validation
→ Skill or Lane registry change
→ audit receipt
```

New Lane activation must default to disabled/reviewable until the activation transaction is explicitly authorized.

---

# 5. Closure Track C — Data Lifecycle, Security, and Recovery

## C-01 Safe Reset Closure

The prior conformance checklist used the label `Safe export/reset`. Verify the actual implementation.

If reset is absent or incomplete, implement an explicit safe reset workflow.

### Requirements

- Director/bootstrap authorization
- optional export-before-reset
- clear scope preview
- no credential value disclosure
- deterministic deletion/reset boundary
- protected runtime/system files excluded
- idempotent/recoverable behavior where reasonable
- canonical receipt
- tests for partial failure

### Gate

A test runtime can export selected state, reset the approved scope, restart, and show that selected data is gone, protected state remains, exported artifacts remain verifiable, and credentials were not leaked.

---

## C-02 Local Encryption Decision

This is a Director decision, not an implementation assumption.

One explicit V1 policy must be selected and documented:

### Option A — Full local database encryption in V1
Vesper state DB and sensitive local stores require encryption-at-rest.

### Option B — Secrets encrypted, primary state DB plaintext-local
Credential values use OS/keychain/secret-store encryption while normal local state remains plaintext SQLite under OS filesystem protection.

### Option C — Encryption deferred after V1
Document threat model, accepted risk, and exact post-v1 requirement.

Do not implement custom cryptography ad hoc.

### Stop condition

If no Director policy exists, mark `C-02 DECISION REQUIRED` and continue all unrelated closure tasks.

---

## C-03 Multi-file Patch Consistency Review

Review the existing approved file application semantics.

Current per-file atomic replace is acceptable only if documentation and recovery semantics state its real guarantees.

Choose one:

- implement PatchSet-wide transactional/rollback behavior, or
- explicitly define and test partial-commit recovery/reconciliation.

### Gate

Inject a failure during a multi-file PatchSet and prove the documented behavior.

---

# 6. Closure Track D — External Adapter Vertical Slice

Do not mark LocalAdapterBoundary tests as a completed real external integration.

## D-01 Real Adapter Interface

Define the provider-neutral production adapter contract for:

- authenticated read
- provenance
- normalized external data
- effect proposal
- approval-gated write
- provider response
- canonical effect receipt
- offline/error behavior
- rate/permission failure behavior
- external instruction/data separation

---

## D-02 First Real Read Adapter

Implement at least one real connected-service read adapter.

Preferred V1 choices should reuse the project's intended personal-OS integrations, such as Google Calendar, Gmail, Google Drive, or GitHub.

Use credential references, never raw credential persistence in Vesper state.

### Gate

```text
external service
→ adapter read
→ provenance-bearing normalized artifact/state
→ Kernel/Vesper storage
→ UI or Process consumption
```

No external text may become trusted instruction merely because it came from the provider.

---

## D-03 First Real Approval-Gated Write Adapter

Implement at least one realistic external write/effect path.

Examples:

- create/update a sandbox Calendar event,
- create a safe test GitHub artifact/issue in a designated sandbox,
- another reversible test integration approved by Director.

### Required path

```text
Process
→ proposed external effect
→ Kernel permission check
→ Director approval when required
→ adapter write
→ canonical receipt
→ reconciliation/read-back
```

### Stop condition

Do not perform live state-changing external actions without the required Director approval and designated test/sandbox target.

---

## D-04 Adapter Recovery

Implement/reconcile:

- provider timeout
- provider unavailable
- expired credential
- permission denied
- rate limit
- ambiguous write result
- duplicate retry

Ambiguous write results must not be blindly replayed.

---

# 7. Closure Track E — Dashboard and Product Conformance

## E-01 Full Daily Workflow Gate

Create a canonical browser-level repeated Director workflow covering the required V1 surfaces without direct DB manipulation or developer-only APIs.

At minimum include:

- Home / daily briefing
- Conversation
- Project/task
- Calendar
- Memory/idea
- Process visibility
- FEL/observability
- Approval
- Connection status
- Settings
- Lane management when applicable

### Gate

Run the workflow, close/restart relevant runtime/browser state, then repeat a second realistic cycle and prove durable continuity.

Do not equate "browser reopen" alone with a repeated daily workflow if the actual interaction cycle is not repeated.

---

## E-02 External Data in Dashboard

When D-track adapter work is available, show normalized connected-service information in the Vesper shell without making the external system authoritative over Vesper state.

Must clearly distinguish:

- Vesper canonical state
- external observations
- pending external effects
- confirmed external effects
- stale/offline connection state

---

## E-03 Product Error States

Ensure the main shell handles:

- no model configured
- model/provider failure
- offline external adapter
- expired credential
- pending approval
- blocked Process
- recovered Process
- stale memory/context
- Lane disabled/retired
- no data / first boot

No silent false success.

---

# 8. Closure Track F — CI and Repository Authority

The repository is now large enough that local agent-reported test counts are not sufficient as the only regression authority.

## F-01 GitHub Actions CI

Add CI on pull request and main push.

Minimum gates:

- Python dependency/install check
- `python -m compileall -q vesper`
- `pytest -q`
- frontend dependency install
- frontend production build
- Playwright E2E
- migration/bootstrap tests
- formatting or diff hygiene checks appropriate to the repo

Cache only when it does not change correctness.

---

## F-02 Canonical Test Evidence Cleanup

Do not use a hard-coded test count as the primary authority.

Prefer:

```text
command
commit SHA
exit status
timestamp/CI run
```

Update documents to report the latest verified run consistently.

---

## F-03 README / Architecture Status Reconciliation

The root README is stale relative to current implementation.

Update it to describe:

- current Vesper architecture
- Vesperest = FEL
- current implemented major capabilities
- what remains blocked/incomplete
- how to run backend/frontend/tests
- where architecture and conformance authority lives

Do not copy stale statements that Lane cognition or ExecutionGraph are future work if they are already implemented.

---

## F-04 Repository-owned Closure Spec

Add this document to the repository, recommended path:

`docs/VESPER_V1_CLOSURE_SPEC.md`

Future Goal sessions must be able to find the authoritative remaining-work spec inside the repo.

---

# 9. Final Vesper v1 Seal Gate

Vesper v1 may be declared SEALED only when all applicable conditions below are true.

## Runtime

- durable Process runtime integration passes
- timer/recurrence/monitoring path uses Kernel scheduling
- restart reconciliation passes
- no false completion after crash
- no duplicate effect after recovery

## FEL

- core Lanes and graph runtime pass
- fallback execution history is durable
- fallback matching supports structural + semantic/operational evidence
- Skill vs Lane recommendation is not hard-coded
- candidate review/approval is durable
- activation remains Director-gated

## Memory

- bounded ContextPack admission passes
- provenance and stale/conflict behavior passes
- restart does not corrupt canonical memory state

## Effects

- file effect semantics are accurately documented and tested
- external write ambiguity is reconciled safely
- approval boundaries cannot be bypassed

## External adapters

- at least one real authenticated read vertical passes
- at least one approved write vertical passes, unless Director explicitly scopes V1 as local-only
- provenance/offline/error/instruction-safety gates pass

## Product

- repeated realistic browser workflow passes
- recovery/error states are visible
- connected data remains non-authoritative external evidence

## Security / data lifecycle

- secret rotation passes
- backup/restore/corruption recovery passes
- safe reset closure passes
- local encryption policy is explicitly resolved or explicitly accepted as deferred

## CI

- required GitHub Actions gates pass on the seal commit

## Documentation

- README reflects actual architecture
- closure checklist matches code evidence
- no stale "completed" claim remains without executable evidence

---

# 10. Implementation Rules for Hermes

For every closure task:

1. Inspect current code and tests first.
2. Do not rebuild working systems.
3. Create the smallest vertical change that closes the actual gap.
4. Add or strengthen executable evidence.
5. Run focused gates.
6. Run the required broader regression gate.
7. Update the repository closure checklist.
8. Continue to the next genuinely incomplete task automatically.

Do not stop because:

- one task completed,
- one Phase completed,
- a test initially failed,
- migration numbering needs adjustment,
- context compression occurred,
- documentation is stale,
- a local implementation detail is inconvenient.

Stop only when:

1. a Core Invariant would need to change,
2. two authoritative Director decisions conflict,
3. a new irreversible/external effect requires approval,
4. a Director policy decision explicitly marked in this spec is required and blocks the next applicable work,
5. every applicable closure gate is complete.

External credential blockers must block only the exact credential-dependent tasks. Continue all unrelated local closure work.

---

# 11. Required Closure Status Format

Maintain a repository-owned status table with:

- Closure ID
- status:
  - NOT STARTED
  - IN PROGRESS
  - IMPLEMENTED WITH EVIDENCE
  - BLOCKED
  - DECISION REQUIRED
- implementation files
- focused gate
- last verified commit
- notes

Do not use a Phase-level green label to hide an incomplete child requirement.

---

# 12. Initial Priority Order

Unless repository evidence requires a different dependency order:

1. F-04 — commit this Closure Spec into the repo
2. A-03 — startup reconciliation audit/integration
3. A-01 — durable runtime state
4. A-02 — Kernel scheduler integration
5. B-01 — durable fallback execution records
6. B-04 — durable candidate review/approval
7. B-02/B-03 — richer matching and Skill-vs-Lane judgment
8. C-01 — safe reset closure
9. C-03 — multi-file patch consistency semantics
10. F-01/F-02/F-03 — CI and repository authority cleanup
11. E-01/E-03 — repeated product workflow and error states
12. D-track — real external adapter verticals when credentials/approval are available
13. C-02 — execute the chosen Director encryption policy
14. Final seal audit

The agent may reorder tasks only when repository dependency evidence justifies it.

---

# 13. Director Decisions Currently Expected

## Decision 1 — Local encryption policy

Choose A, B, or C from C-02 before final v1 seal.

Until decided:
- do not invent encryption architecture,
- continue unrelated tasks.

## Decision 2 — External adapter V1 scope

Default assumption for this spec:

V1 should demonstrate at least one real read and one real approval-gated write adapter in a designated test/sandbox environment.

If the Director explicitly chooses a local-only V1, document the deferred adapter gate and adjust the final seal criteria accordingly.

---

# 14. Final Completion Report

When Hermes believes Vesper v1 is ready to seal, it must produce a final report containing:

- baseline commit
- final commit
- closure tasks completed
- tasks blocked/deferred by explicit Director decision
- exact test/build/CI commands
- CI run evidence
- remaining known limitations
- external-effect evidence
- security policy decision
- recovery evidence
- final statement:
  - `VESPER V1 SEALED`, or
  - `VESPER V1 NOT SEALED`

Never use `SEALED` when a required gate is merely inferred.

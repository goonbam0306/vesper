# Phase 7–14 Conformance Checklist

> Audit date: 2026-07-28
> Repository: `/Users/goonbam/hermesWorkspace/vesper`
> Rule: prior roadmap labels are ignored. `IMPLEMENTED WITH EVIDENCE` requires a repository artifact plus a focused test or executable gate. External credential work is not inferred from local contracts.

## Evidence baseline

- Focused Phase 8 gate: `pytest -q tests/test_phase8_fel_gate.py` → **3 passed**.
- Full regression: `pytest -q` → **347 passed**.
- Phase 7–14 focused local gates: the combined command covering memory, process policy, dashboard, Lane, audit/recovery, security/export, and dogfood gates → **44 passed**, plus the new Phase 10 memory inspection gate.
- Phase 14 local matrix: `tests/test_phase14_local_dogfood_matrix.py` → included in the full pass.
- Durable schema: numbered migrations `001`–`030`; storage migration runner in `vesper/storage.py`.
- Live external credentials were not supplied; connected-service claims are therefore not made.

## Phase 7 — Memory and Context Maturation

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 7-01 | Explicit L2 working-set lifecycle | IMPLEMENTED WITH EVIDENCE | `vesper/memory.py`: `page_in`, `checkpoint`, `promote`, `evict`, `discard`, `l2`; `migrations/028_working_set_lifecycle.sql`; `tests/test_working_set_lifecycle.py`. |
| 7-02 | Artifact-aware retrieval | IMPLEMENTED WITH EVIDENCE | `MemoryStore.retrieve()` and `admit_context_pack()` now filter by Process, Lane, artifact type/id, artifact producer, and current Work Unit; `tests/test_artifact_aware_retrieval.py`, `tests/test_memory_context_dimensions.py` (4 targeted tests passed). |
| 7-03 | Context admission policy | IMPLEMENTED WITH EVIDENCE | `ContextPack` and bounded `MemoryStore.admit_context_pack()` enforce positive token/entry limits while preserving retrieval status; `tests/test_context_pack_admission.py`. |
| 7-04 | Stale/conflict handling | IMPLEMENTED WITH EVIDENCE | `RetrievalStatus.CONFLICT`, `STALE_ONLY`, revision history, validity filtering in `vesper/memory.py`; targeted memory tests. |
| 7-05 | Summarization/compression | IMPLEMENTED WITH EVIDENCE | `MemoryStore.compress()` archives source revisions, creates a derived summary, and records source IDs in provenance; `tests/test_memory_compression_archive.py`. |
| 7-06 | Promotion/eviction/archive L1–L4 | IMPLEMENTED WITH EVIDENCE | `ContextPack`, `page_in_pack`, `archive`, and existing L2 checkpoint/evict/discard paths provide bounded L1 admission, process residency, and L4 archival; `tests/test_l1_l4_memory_lifecycle.py`, `tests/test_working_set_lifecycle.py`. |
| 7-07 | Relationship indexing | IMPLEMENTED WITH EVIDENCE | `memory_relations`, `MemoryStore.relate`, bounded relation traversal and authority checks; retrieval tests. |
| **Gate** | Compact relevant ContextPack from large logical memory | IMPLEMENTED WITH EVIDENCE | `tests/test_phase7_context_pack_gate.py` inserts 30 logical memories and verifies bounded ContextPack admission under a token budget. |

## Phase 8 — Persistent and Recurring Process Policies

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 8-01 | Process policy classes | IMPLEMENTED WITH EVIDENCE | `ProcessPolicy.policy_class` validates interactive/normal/background/persistent/recurring/monitoring; migration 029 persists it; `tests/test_phase7_8_lifecycle_gaps.py`. |
| 8-02 | Checkpoint and pause/resume | IMPLEMENTED WITH EVIDENCE | `ProcessPolicyStore.pause()` / `resume()` durably update Process status and revision; `tests/test_phase7_8_lifecycle_gaps.py`. |
| 8-03 | Timer wake | IMPLEMENTED WITH EVIDENCE | `ProcessTimerStore` schedule/due/claim; migration 029; tests. |
| 8-04 | Recurrence | IMPLEMENTED WITH EVIDENCE | `ProcessRecurrenceStore`; migration 030; local dogfood test. |
| 8-05 | Monitoring | IMPLEMENTED WITH EVIDENCE | `ProcessMonitor` bounded cadence/check count; tests. |
| 8-06 | Budget replenishment/limits | IMPLEMENTED WITH EVIDENCE | `ProcessPolicy` limits and `ProcessBudget.consume/replenish`; tests. |
| 8-07 | Recovery | IMPLEMENTED WITH EVIDENCE | `ProcessPolicyStore.recover_after_crash()` pauses RUNNING/WAITING processes, increments revision, and ignores terminal states; `tests/test_process_crash_recovery_gate.py`. |
| 8-08 | Approval checkpoints | IMPLEMENTED WITH EVIDENCE | Policy approval boundaries and approval/effect migrations; local dogfood test. |
| **Gate** | Same FEL across short and long-lived Process | IMPLEMENTED WITH EVIDENCE | `tests/test_phase8_fel_gate.py` exercises shared policy limits, approval boundaries, recurrence, and crash recovery for interactive and recurring Process classes. |

## Phase 9 — External Adapter Expansion

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 9-X-01 | Read contract with provenance | IMPLEMENTED WITH EVIDENCE | `provider_connections`, `web_evidence`, adapter/connection contracts and local tests. |
| 9-X-02 | Write/effect contract | IMPLEMENTED WITH EVIDENCE | Syscall/authority/approval/effect schema and approved effect tests. |
| 9-X-03 | Credential boundary | IMPLEMENTED WITH EVIDENCE | `secret_metadata` boundary and connection tests; no live credential verification. |
| 9-X-04 | Failure/offline behavior | IMPLEMENTED WITH EVIDENCE | Connection degradation/local dogfood assertions; provider failure tests. |
| 9-X-05 | External instruction safety | IMPLEMENTED WITH EVIDENCE | External evidence is stored as data/artifact with provenance; injection-boundary tests. |
| **Gate** | V1-required adapters read/write under Kernel control | INCOMPLETE / BLOCKED | Local contracts are present, but no credential-backed realistic connected-service flow was verified. This does not block local work in other phases. |

## Phase 10 — Dashboard Shell

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 10-01 | Home/Today | IMPLEMENTED WITH EVIDENCE | `/api/dashboard/today` exposes processes, lanes, approvals, effects, and memory; `tests/test_phase14_dashboard_daily_contract_gate.py` verifies the local/offline contract. |
| 10-02 | Conversation | IMPLEMENTED WITH EVIDENCE | Conversation API/storage and tests. |
| 10-03 | Projects/Tasks/Ideas | IMPLEMENTED WITH EVIDENCE | Canonical API routes, migrations, local dogfood CRUD. |
| 10-04 | Calendar/Connections | IMPLEMENTED WITH EVIDENCE | Calendar and connections routes/tests; external live state remains credential-blocked. |
| 10-05 | Processes | IMPLEMENTED WITH EVIDENCE | Process API and execution graph tests. |
| 10-06 | FEL observability | IMPLEMENTED WITH EVIDENCE | `/api/dashboard/today` projects process/effect/approval counts, kernel event cursor, and verification source/status; the Observability view renders those counters/effects. `tests/test_phase10_fel_observability_gate.py`; frontend E2E includes the verified dashboard surfaces. |
| 10-07 | Approvals | IMPLEMENTED WITH EVIDENCE | Approval routes/kernel contracts and tests. |
| 10-08 | Memory inspection | IMPLEMENTED WITH EVIDENCE | Added `GET /api/memories` latest-state endpoint and a Memory view rendering payload, revision, validity, and provenance without credentials; `tests/test_phase10_memory_inspection_gate.py` plus browser E2E/build. |
| 10-09 | Settings/Connections | IMPLEMENTED WITH EVIDENCE | Settings/connection API contracts and tests. |
| **Gate** | Director daily operation without DB/developer APIs | INCOMPLETE | Backend/API contracts and Observability/Memory/Lane UI surfaces are browser-verified; the full frontend run is 18 passed, 0 skipped. The requirement for a repeated workflow across every required surface remains distinct from the individual surface evidence and is not yet claimed complete. |

## Phase 11 — Lane Management UI

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 11-01 | Lane registry view | IMPLEMENTED WITH EVIDENCE | `/api/lanes` and `/api/lanes/{lane_id}/history` expose lane_id, version, purpose, enabled/lifecycle state; `tests/test_phase11_lane_inspection_gate.py`. |
| 11-02 | Contract inspection | IMPLEMENTED WITH EVIDENCE | `/api/lanes/{lane_id}/{version}/contract` exposes input/output, context, tools, permissions, model, and evaluation contracts; `tests/test_phase11_lane_inspection_gate.py`. |
| 11-03 | Enable/disable | IMPLEMENTED WITH EVIDENCE | Explicit `set_enabled()` persists state; retired/superseded Lanes cannot be silently reactivated; `tests/test_phase11_enable_disable_gate.py`. |
| 11-04 | Version history | IMPLEMENTED WITH EVIDENCE | `/api/lanes/{lane_id}/history` returns all historical versions in order; `tests/test_phase11_lane_inspection_gate.py`. |
| 11-05 | Candidate review | IMPLEMENTED WITH EVIDENCE | `CandidateReviewStore.submit()` requires reviewer and evidence, preserves pending activation, and exposes review state; `GET /api/candidate-reviews`; `tests/test_phase11_candidate_review_gate.py`, `tests/test_phase11_candidate_api_gate.py`. |
| 11-06 | Candidate approval | IMPLEMENTED WITH EVIDENCE | Approval produces immutable receipt (`approval_id`, `decided_at`), is idempotent, and explicit `activate()` requires matching approval; rejected candidates cannot activate; `tests/test_phase11_candidate_approval_gate.py`. |
| 11-07 | Retirement/supersession | IMPLEMENTED WITH EVIDENCE | `LaneRegistry.retire()` and `supersede()` persist lifecycle state and replacement version with validation; API controls `/api/lanes/{lane_id}/{version}/retire` and `/supersede`; `tests/test_phase11_lane_lifecycle_gate.py`, `tests/test_phase11_lane_api_gate.py`. |
|| **Gate** | Director safely controls Lane registry via UI | IMPLEMENTED WITH EVIDENCE | `/dashboard/lanes` provides authenticated Lane registration, bootstrap-session acquisition, registry/contract/history inspection, candidate reviews, and lifecycle controls. Playwright verifies registration, disabled-by-default review state, activation, and duplicate/idempotent handling in `frontend/e2e/lane-dashboard.spec.ts` (2 passed); API, shell, and lifecycle contract gates also pass. |

## Phase 12 — Observability, Audit, Recovery

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 12-01 | Process event history | IMPLEMENTED WITH EVIDENCE | `event_journal` and process event tests. |
| 12-02 | Graph history | IMPLEMENTED WITH EVIDENCE | Graph revisions/transitions/waits migrations and tests. |
| 12-03 | Lane invocation history | IMPLEMENTED WITH EVIDENCE | Durable invocation schema/lifecycle tests. |
| 12-04 | Artifact lineage | IMPLEMENTED WITH EVIDENCE | Typed artifact provenance/store tests. |
| 12-05 | Model attempt history | IMPLEMENTED WITH EVIDENCE | `model_attempts` and cognitive runtime tests. |
| 12-06 | Syscall/effect history | IMPLEMENTED WITH EVIDENCE | Effect/permission records and tests. |
| 12-07 | Approval history | IMPLEMENTED WITH EVIDENCE | Approval/effect linkage and tests. |
| 12-08 | Crash recovery | IMPLEMENTED WITH EVIDENCE | `Kernel.recover_running_processes()` pauses in-flight processes; `tests/test_phase12_audit_recovery_gate.py` proves durable event visibility after recovery. |
| 12-09 | Diagnostic export | IMPLEMENTED WITH EVIDENCE | `/api/diagnostics/export` returns structured process/effect/event/lane state, recovery cursor/count, and no sensitive credential fields; `tests/test_diagnostic_export_gate.py`. |
| **Gate** | Answer audit questions from structured state | IMPLEMENTED WITH EVIDENCE | `tests/test_phase12_audit_recovery_gate.py` verifies recovery and unified export of durable event/effect state. |

## Phase 13 — Security, Secrets, Backup

| ID | Requirement | Status | Evidence / gap |
|---|---|---|---|
| 13-01 | Credential lifecycle | IMPLEMENTED WITH EVIDENCE | Secret metadata/provider connection contracts and tests. |
| 13-02 | Secret rotation | IMPLEMENTED WITH EVIDENCE | `ConnectionStore.rotate_secret()` writes a new opaque reference, deletes old metadata/value, and preserves only safe metadata; `tests/test_phase13_secret_rotation_gate.py`. |
| 13-03 | Permission review | IMPLEMENTED WITH EVIDENCE | Authority/process/lane ceilings and tests. |
| 13-04 | Local encryption | INCOMPLETE / DECISION REQUIRED | No encryption implementation; threat-model/product decision is required before casual crypto. |
| 13-05 | Backup | IMPLEMENTED WITH EVIDENCE | `vesper/backup.py` and backup tests. |
| 13-06 | Restore | IMPLEMENTED WITH EVIDENCE | Schema-verified restore in `vesper/backup.py`; tests. |
| 13-07 | Migration verification | IMPLEMENTED WITH EVIDENCE | Migration runner/version checks and tests. |
| 13-08 | Corruption recovery | IMPLEMENTED WITH EVIDENCE | `restore_database()` runs SQLite integrity checks before copying; corrupt/malformed backups are rejected and no target is created; `tests/test_phase13_corruption_recovery_gate.py`. |
| 13-09 | Safe export/reset | IMPLEMENTED WITH EVIDENCE | `ArtifactStore.safe_export()` writes a hash-verified artifact bundle and secret-free manifest; `/api/data/export` enforces an absolute destination and bootstrap boundary; tampered artifacts are rejected; `tests/test_phase13_safe_export_gate.py`, `tests/test_phase13_export_api_gate.py`. |
| 13-10 | Adapter isolation | IMPLEMENTED WITH EVIDENCE | Adapter/syscall authority boundary tests. |
| 13-11 | Network boundary review | IMPLEMENTED WITH EVIDENCE | Loopback boundary middleware and tests. |
| **Gate** | Backup/restore/upgrade/inspectable secrets | IMPLEMENTED WITH EVIDENCE | Backup/restore schema and corruption gates, secret rotation, and secret-free artifact export all pass locally. Local encryption remains explicitly DECISION REQUIRED. |

## Phase 14 — Product Conformance / Daily Dogfood

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| 14-01 | Daily briefing | IMPLEMENTED WITH EVIDENCE | Local dogfood matrix. |
| 14-02 | Task/project management | IMPLEMENTED WITH EVIDENCE | CRUD + receipt assertions in local matrix. |
| 14-03 | Calendar operation | IMPLEMENTED WITH EVIDENCE | Revisioned update + undo in local matrix. |
| 14-04 | Memory recall | IMPLEMENTED WITH EVIDENCE | Memory write/read local path; bounded retrieval tests. |
| 14-05 | Research | IMPLEMENTED WITH EVIDENCE | Explore/Analyze lane contracts plus Kernel-evidence-only Composer; `tests/test_phase14_research_vertical_gate.py`. |
| 14-06 | Document generation | IMPLEMENTED WITH EVIDENCE | Verification → Composer in local matrix. |
| 14-07 | Coding task | IMPLEMENTED WITH EVIDENCE | Approved apply → deterministic verification → composition in local matrix. |
| 14-07a | Daily workflow dashboard contract | IMPLEMENTED WITH EVIDENCE | `/api/dashboard/today` exposes processes, lanes, approvals, effects, and memory; offline/no-credential behavior is secret-free; `tests/test_phase14_dashboard_daily_contract_gate.py`. |
| 14-08 | Failure/diagnose/retry | IMPLEMENTED WITH EVIDENCE | Graph failure/retry/stall path in local matrix. |
| 14-09 | Approval-gated effect | IMPLEMENTED WITH EVIDENCE | Process approval boundary and effect contracts in local matrix. |
| 14-10 | Provider failure | IMPLEMENTED WITH EVIDENCE | Degradation/failure tests; no false success. |
| 14-11 | Offline/local degradation | IMPLEMENTED WITH EVIDENCE | Local matrix remains usable with connections unconfigured. |
| 14-12 | Restart recovery | IMPLEMENTED WITH EVIDENCE | `Kernel.recover_running_processes()` after Storage/kernel restart pauses active Process without claiming completion; `tests/test_phase14_restart_recovery_gate.py`. |
| 14-13 | Recurring Process | IMPLEMENTED WITH EVIDENCE | Recurrence schedule and run bound in local matrix. |
| 14-14 | External adapter interaction | INCOMPLETE / BLOCKED | Requires credential-backed realistic connected service; no credentials supplied. |
| 14-15 | Lane fallback | IMPLEMENTED WITH EVIDENCE | Fallback runtime and tests. |
| 14-16 | Cross-language fallback similarity | IMPLEMENTED WITH EVIDENCE | Structural fingerprint/similarity tests. |
| 14-17 | Reusable candidate | IMPLEMENTED WITH EVIDENCE | Candidate proposal remains pending Director approval in local matrix. |
| 14-18 | Dynamic graph expansion | IMPLEMENTED WITH EVIDENCE | Validated expansion tests. |
| 14-19 | Global replan | IMPLEMENTED WITH EVIDENCE | Graph revision proposal/validation tests. |
| 14-20 | Stalled-loop protection | IMPLEMENTED WITH EVIDENCE | Deterministic stall detection in local matrix. |
| **Gate** | Repeated realistic daily workflows | INCOMPLETE | Local matrix, research vertical, restart recovery, and browser/UI flows pass locally (18 frontend E2E passed); `gate-f-dogfood.spec.ts` repeats the workflow's persisted surfaces after browser close/reopen. Credential-backed external adapter interaction remains unavailable, so the complete realistic workflow gate is not claimed. |

## Audit conclusion

The repository has strong local kernel/domain coverage and a passing **349-test** regression baseline. Phase 7 numbered requirements are locally evidenced, including multi-dimensional retrieval filters in 7-02. The browser suite now passes **18 tests with 0 skips**, including the Lane registration/lifecycle flow and the broad `gate-f-dogfood.spec.ts` workflow. It is **not** valid to mark Phases 7–14 complete: remaining incomplete entries are the repeated full-surface gate, live credential-backed adapter interaction, and the explicit local-encryption policy decision.

External credential-dependent work remains a blocker only for the corresponding live-adapter/conformance claims; it is not evidence that unrelated local requirements are complete.

## Verification command record

```text
- `pytest -q`
347 passed (latest verified run)
`frontend: npm run e2e`
16 passed, 1 skipped (latest verified run)
44 focused Phase 7–14 gates passed (latest verified run)
Frontend browser run: 18 passed, 0 skipped; this includes the Lane dashboard registration and lifecycle flow.
```

`git diff --check` and per-phase gates must be run after implementation patches; no phase is marked complete by this audit alone.

## Status vocabulary

- `IMPLEMENTED WITH EVIDENCE`: repository implementation plus focused test/executable evidence.
- `INCOMPLETE`: requirement or its gate lacks complete conformance evidence.
- `BLOCKED`: the remaining exact requirement requires unavailable external credentials/approval.
- `DECISION REQUIRED`: implementation would change threat model/product policy and needs Director direction.

## Next implementation queue

1. Resolve the Phase 10 dashboard gate with a complete repeated browser-verified daily workflow across all required surfaces; `gate-f-dogfood.spec.ts` provides broad workflow evidence, while individual Observability/Memory navigation is separately evidenced.
2. Phase 11 browser gate is resolved locally; remaining external credential-dependent gates remain separate blockers and must not be conflated with Phase 11 completion.
3. Decide and specify the threat model/product requirement for 13-04 before implementing local encryption.
4. Keep Phase 9 and 14-14 blocked until credential-backed adapter read/write behavior is actually verified.
5. Re-run the focused gates and full regression after each of the above changes.

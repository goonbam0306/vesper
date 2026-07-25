# Dogfood Product Closure 4.1 — Project Relation Schema Audit

Source of truth inspected:

- `migrations/005_phase4_core_apps.sql`
- `migrations/003_phase2_memory_runtime.sql`
- `vesper/core_apps.py`
- `vesper/api.py`

## Relation truth table

| Entity | Project relation | Evidence |
|---|---|---|
| Task | EXISTS | `tasks.project_id TEXT REFERENCES projects(project_id)` in migration 005; indexed by `idx_tasks_project` |
| Calendar/Event | EXISTS | `calendar_items.project_id TEXT REFERENCES projects(project_id)` in migration 005 |
| Idea | DOES_NOT_EXIST | Ideas are stored as `memories(kind='IDEA')`; `memories` has no `project_id` and no project relation contract |
| Process | DOES_NOT_EXIST | `processes` has no `project_id` and no project relation contract |
| Risk | DOES_NOT_EXIST | No canonical Risk table/model or project relation found |
| Decision | DOES_NOT_EXIST | No canonical Decision table/model or project relation found |
| Note | DOES_NOT_EXIST | No canonical Note table/model or project relation found |

## Project Detail MVP

The MVP may truthfully expose:

- Overview: project `name`, `status`, `objective`
- Tasks: rows whose canonical `tasks.project_id` equals the selected project
- Calendar: rows whose canonical `calendar_items.project_id` equals the selected project

Ideas, Notes, Risks, Decisions, and Processes are not projected because their canonical project relationships do not exist. No ad-hoc foreign keys are added. Unsupported sections should be omitted or shown as an honest `Not linked yet` state; they must not imply a relationship that the schema does not contain.

## Future architecture note

If heterogeneous objects need project association, evaluate a first-class relation contract before adding `project_id` to every table. Conceptually:

```text
entity_relations(
  relation_id,
  source_type,
  source_id,
  relation_type,
  target_type,
  target_id,
  provenance,
  created_at
)
```

This note does not authorize implementing that contract in Closure 4.1.

## Action scope note

```text
SUPPORTED_CHAT_ACTION = CREATE_TASK
```

The deterministic recognizer is a bounded dogfood MVP slice, not a general natural-language action system. A model response without a canonical action receipt is not evidence that a state-changing action occurred. The invariant remains:

> Never claim that a state-changing action was completed unless a canonical action receipt is present.

Closure 4.1 must preserve this contract for unsupported requests as well.

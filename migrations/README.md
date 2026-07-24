# Migration identity rules

Migration numbers represent chronological schema revisions, not Vesper implementation phases.

- The numeric prefix is the only ordering authority. The runner parses and sorts it as an integer.
- A revision number is unique and is recorded exactly once after its SQL succeeds.
- An applied revision's filename identity and SHA-256 checksum are verified on later startups.
- Phase or Gate names are filename descriptions only; a later Phase 2/Gate D change receives the next chronological revision number.
- Do not rename, renumber, edit, or delete an applied migration. Add a later corrective migration instead.

The lightweight runner preserves compatibility with legacy `schema_migrations(version)` records by backfilling identity metadata on the first safe startup.

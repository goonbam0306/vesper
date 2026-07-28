# Vesper

Vesper is a local-first deterministic runtime whose Kernel validates and executes proposed work.

## Closure status

The authoritative v1 closure contract is [`docs/VESPER_V1_CLOSURE_SPEC.md`](docs/VESPER_V1_CLOSURE_SPEC.md).
Executable evidence and the current seal conclusion are maintained in [`docs/VESPER_V1_CLOSURE_STATUS.md`](docs/VESPER_V1_CLOSURE_STATUS.md).

Current repository status: **VESPER V1 NOT SEALED** until all applicable closure gates pass and the required Director decisions are recorded.

## Verification

```bash
pip install -e '.[test]'
pytest -q
git diff --check
```

## Runtime boundaries

Validated routing is limited to DIRECT, LANE, GRAPH-deferred, and FALLBACK materialization. The Kernel remains deterministic authority; cognition is replaceable and proposals require validation before effects.

## Historical implementation notes

Earlier phase implementation notes remain in repository history. They are not seal evidence; use the closure status document and executable tests as the source of truth.

## License

See repository metadata for licensing.

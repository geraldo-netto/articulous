# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to the `articulous/` package.

---

## security

_(all open items resolved; tracked via git history)_

## performance

_(all open items resolved; tracked via git history)_

## scalability

_(all open items resolved; tracked via git history)_

## concurrency

_(all open items resolved; tracked via git history)_

## code complexity

_(all open items resolved; tracked via git history)_

## code duplication

_(all open items resolved; tracked via git history)_

## architecture/modularity/SOLID

_(all open items resolved; tracked via git history)_

## decoupling

_(all open items resolved; tracked via git history)_

## business/design patterns/DDD

_(all open items resolved; tracked via git history)_

## reliability/correctness

_(all open items resolved; tracked via git history)_

## observability

_(all open items resolved; tracked via git history)_

## wiring gaps

_(all open items resolved; tracked via git history)_

## unused functions/methods

_(all open items resolved; tracked via git history)_

## documentation

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DOC-02 | open | S | `TransformEngine.run` (engines.py:68) has no method-level docstring | Template-method dispatch; class docstring covers intent but the method override contract is not stated. Add one line: behaviour, dry-run, return. |

---

## Open — parked

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-01 | parked | S | `_stream_projections` (pipeline.py:504) emits no per-section progress; only final tally logs at pipeline.py:571 | Deliberate to keep production logs quiet; revisit if very large sites need progress feedback. |
| OBS-02 | parked | S | `timed()` (runtime.py:118) wraps tasks at DEBUG only; production builds see no per-task signal | Same trade-off as OBS-01; bumping to INFO would flood logs for normal builds. |
| DOC-01 | parked | S | `SiteModelCtx` `@property` members (models.py:33-46) carry no docstrings | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |

## Audit picks deliberately rejected

| id | description | reason |
|----|-------------|--------|
| PERF-01 | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| SCAL-01 | Tag-page build is O(T*A) per language | Bound is per-language and per-tag, acceptable for any realistic site. |
| CC-01 | `_stream_projections` accumulates 3 lists + heap in single pass | Density is the point of single-pass streaming; splitting would re-walk articles. |
| DUP-01 | 5 section builders follow the same pattern | Each builder is 3-5 lines; extracting a helper would obscure not clarify. |
| REL-01 | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |
| REL-02 | `_stream_projections` skips filter failures; final count reflects post-filter total | Correct by design; the logged "Discovered N" describes what was built. |
| UNUSED-01 | `deep_merge` (config.py:53) used only by `load_or_create_config` | Internal helper with direct unit tests; keep. |
| UNUSED-02 | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) called only from `_collect_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |

# TODO

For retained `wont_fix` decisions, `—` means no implementation effort was estimated.
Existing estimates describe the declined work.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-14 | open | low | medium | Scalability: fingerprint, ownership and route maps for the whole corpus stay in memory through render. | `pipeline.py:1941-1949,718-748`, `ownership.py:142-157`; acknowledged in `docs/architecture.md:132-133`. tracemalloc: 16.8 MB live and 32.2 MB peak at 4,000 articles, 58.7 and 111.9 MB at 12,000 with three languages, about 0.5 GB live at 100k. About 72% is decoded cache and ownership JSON. Next: apply the size reductions from the full-state rewrite row in Cache persistence, then remeasure. |
| REVIEW28-15 | open | low | small | Wiring gap: the engine protocol requires `ExecutionCapabilities.external_process`, but no production decision reads it. | Worker documentation now describes CPU-based sizing and the public process indicator. Commit bdcaeaa removed the only reader; grep finds only `transform_contracts.py:13,16` and the `_DeferredEngine` pass-through, yet `require_transform` still demands `capabilities`. Next: decide whether the process indicator belongs in the required protocol and update its callers or remove that requirement. |
| REVIEW28-19 | blocked | low | medium | Wiring gap/docs: transform engines are listed as a site extension point but no public entry point accepts one. | `docs/architecture.md:182-183` and `docs/generator-composition.md:354-355` versus the signatures of `run_build`, `prepare_build`, `check_build` and `build_site`; engines come only from `make_engine` (`pipeline.py:181-184,1595-1599`) and configured names. The only test with an independent engine replaces `BuildCtx.engines` and calls private helpers (`tests/test_transform_contracts.py:52-70`). Blocked on an owner decision: add a public admission route or reword both docs to call the protocol an internal seam. |
| PERF-01 | wont_fix | low | — | Performance: XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | low | — | Performance: In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| DUP-01 | wont_fix | low | — | Code duplication: Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| UNUSED-02 | wont_fix | low | — | Unused functions: `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | low | — | Documentation: private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | low | — | Code duplication: `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |


## Article discovery and models

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| SCAL-01 | wont_fix | low | — | Scalability: Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | low | — | Code complexity: `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| REL-02 | wont_fix | low | — | Reliability/correctness: `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |


## Cache persistence

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-27 | blocked | medium | medium | Performance/scalability: all fingerprint state is rewritten in full on every build, including a no-op, once the clock advances a second. | `output_cache.py:44`, `runtime.py:113`, `pipeline.py:2001-2002`, `ownership.py:160-177`. Measured: no-op rewrites 1.3 MB at 1,000 articles and 5.1 MB at 4,000 (0 with the clock frozen); the default shared layout rewrites all four roots (5.2 MB); a one-article edit at 4,000 writes 5.11 MB of cache plus 2.92 MB of ownership. 39% of the cache is the full article-parameter JSON per fingerprint (`pipeline.py:1068`) and 22% is `__routes__`, duplicated in ownership. Contradictions review: `docs/output.md:116-119` documents the timestamp refresh. Blocked on an owner decision on timestamp granularity or location; then store a parameter digest plus the two fields `translation_history` reads and stop duplicating routes. Keep retention expiry including `cache_retention_days: 0`. |
| REL-01 | wont_fix | low | — | Reliability/correctness: `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Generated-site validation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Sitemap generation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Configuration

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| UNUSED-01 | wont_fix | low | — | Unused functions: Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `config.normalize_configuration`, with direct unit tests; keep. |


## Taxonomy authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REDOS-001 | wont_fix | medium | S | Optional taxonomy matcher can retry quadratically on separator-leading names. | Security/performance review; taxonomy_completeness.py:31-44: tag `-a` produces an unanchored separator run followed by `a`; searching whitespace ending in `!` retries the run from each position. Local missing_tags cases at 1k/2k/4k characters took about 5/21/79 ms; no default build caller, only the opt-in public helper. Owner instruction 2026-10-24: stop content-focused analysis and let these findings go; no post code was executed. Declined for this pass; reconsider only on explicit owner resumption. Any future fix requires permanent failing-before/passing-after scaling/semantic controls, including literal punctuation and valid phrase boundaries. Evidence/scope: reviews/regex/README.md. |


## Browser code highlighting

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REDOS-002 | wont_fix | medium | M | Optional synchronous Prism highlighting has content-sensitive quadratic paths. | Security/performance review; code-blocks.js:30 calls highlightElement without a worker or admission bound. Packaged markup tag, Bash function and batch set-variable patterns show roughly 4x cost per doubled input in completed 1k–8k local text-only cases; no snippet was executed. Owner instruction 2026-10-24 declines further post-content/highlighting analysis and hardening. Keep disposition unless owner explicitly resumes. Future work must retain normal highlighting/copy behavior and permanent malformed-input/valid-boundary regressions, with owned cancellation if isolation is selected. Limited evidence and intentionally stopped vendor review: reviews/regex/README.md. |


## Browser search

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Source editing

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Translation authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Local preview

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-68 | wont_fix | low | small | Verification: six site fixture XSLT stylesheets are outside the packaged-template complexity inventory. | Owner decision 2026-11-21: retain the packaged XSLT scope. The fixture article template measures 10 and its top-level declarations are outside the gate parser. Reconsider only if the owner reopens fixture measurement. |


## Packaged content stylesheet

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Documentation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|

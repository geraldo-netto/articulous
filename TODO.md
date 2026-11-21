# TODO

Effort `—` means no change is planned for a retained `wont_fix` decision.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-14 | open | low | medium | Scalability: fingerprint, ownership and route maps for the whole corpus stay in memory through render. | `pipeline.py:1941-1949,718-748`, `ownership.py:142-157`; acknowledged in `docs/architecture.md:132-133`. tracemalloc: 16.8 MB live and 32.2 MB peak at 4,000 articles, 58.7 and 111.9 MB at 12,000 with three languages, about 0.5 GB live at 100k. About 72% is decoded cache and ownership JSON. Next: apply the size reductions from the full-state rewrite row in Cache persistence, then remeasure. |
| REVIEW28-15 | open | low | small | Wiring gap: the engine protocol requires `ExecutionCapabilities.external_process`, but no production decision reads it. | Worker documentation now describes CPU-based sizing and the public process indicator. Commit bdcaeaa removed the only reader; grep finds only `transform_contracts.py:13,16` and the `_DeferredEngine` pass-through, yet `require_transform` still demands `capabilities`. Next: decide whether the process indicator belongs in the required protocol and update its callers or remove that requirement. |
| REVIEW28-16 | open | low | small | Unused: `engines.stylesheet_hash` has no production caller. | `engines.py:140-141`, exported in `__all__` (`:52`); only `tests/test_pipeline.py` and `tests/test_engines.py` use it, production uses `engine.prepare_stylesheet`. Recommendation: delete and move the two tests to `prepare_stylesheet`, unless the owner keeps it as a documented public helper. Next: owner keep or delete decision. |
| REVIEW28-17 | open | low | small | Wiring gap: `TempWorkspace.add` and the `dry_run` argument of `ensure_parent_dir` are used only by tests. | `filesystem.py:371-373` (only `tests/test_runtime.py:471`) and `filesystem.py:23-26` (production callers at `:242`, `:324` never pass it; only `tests/test_runtime.py:73`). Recommendation: delete both with their tests. Next: owner keep or delete decision. |
| REVIEW28-19 | blocked | low | medium | Wiring gap/docs: transform engines are listed as a site extension point but no public entry point accepts one. | `docs/architecture.md:182-183` and `docs/generator-composition.md:354-355` versus the signatures of `run_build`, `prepare_build`, `check_build` and `build_site`; engines come only from `make_engine` (`pipeline.py:181-184,1595-1599`) and configured names. The only test with an independent engine replaces `BuildCtx.engines` and calls private helpers (`tests/test_transform_contracts.py:52-70`). Blocked on an owner decision: add a public admission route or reword both docs to call the protocol an internal seam. |
| PERF-01 | wont_fix | low | — | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | low | — | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| DUP-01 | wont_fix | low | — | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| UNUSED-02 | wont_fix | low | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | low | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | low | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |


## Article discovery and models

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| SCAL-01 | wont_fix | low | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | low | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| REL-02 | wont_fix | low | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |


## Cache persistence

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-26 | blocked | medium | small | Contradictions: legacy route-metadata recovery from the cache no longer works for any real legacy ownership sidecar. | `docs/generator-composition.md:142-143` says legacy ownership can recover known metadata from its cache once; `pipeline.py:2240-2241` discards `__routes__` whenever the sidecar has no generation, and every sidecar old enough to lack `routes` also lacks `generation` (added in 5a3f0b2). Reproduced: pre-generation and version-1 sidecars fail with `Retained route metadata unavailable; run a full build`; the 7dfd2c7 tree recovered them. `tests/test_durable_routes.py:84-103` passes only because it keeps `generation`, a state no released writer produced. Fails safe. Blocked on an owner decision: keep `__routes__` as a one-time fallback when the sidecar has no generation, or delete the sentence and the dead fallback. |
| REVIEW28-27 | blocked | medium | medium | Performance/scalability: all fingerprint state is rewritten in full on every build, including a no-op, once the clock advances a second. | `output_cache.py:44`, `runtime.py:113`, `pipeline.py:2001-2002`, `ownership.py:160-177`. Measured: no-op rewrites 1.3 MB at 1,000 articles and 5.1 MB at 4,000 (0 with the clock frozen); the default shared layout rewrites all four roots (5.2 MB); a one-article edit at 4,000 writes 5.11 MB of cache plus 2.92 MB of ownership. 39% of the cache is the full article-parameter JSON per fingerprint (`pipeline.py:1068`) and 22% is `__routes__`, duplicated in ownership. Contradictions review: `docs/output.md:116-119` documents the timestamp refresh. Blocked on an owner decision on timestamp granularity or location; then store a parameter digest plus the two fields `translation_history` reads and stop duplicating routes. Keep retention expiry including `cache_retention_days: 0`. |
| REL-01 | wont_fix | low | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-39 | open | low | medium | Scalability: publication materialises every route and the whole cache in memory. | `publication_adapter.py:16-40` (`route_values()` at `:31`, one `json.dumps` string at `:25`, encoded again in `backends/posix.py:154`). tracemalloc around `publish_generation`: 5.5 MB at 1,119 outputs and 21.3 MB at 4,269 (4.8-4.9 KiB per output), about 0.5 GB at 100k. Opt-in. Next: stream the cache JSON to its staged file while hashing and hand backends a route iterator; keep the `PublicationInput` mapping contract and the journal cache digest. |


## Generated-site validation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Sitemap generation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Configuration

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| UNUSED-01 | wont_fix | low | — | Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `config.normalize_configuration`, with direct unit tests; keep. |


## Taxonomy authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-53 | open | low | medium | Scalability: near-duplicate reporting still scores a constant fraction of all tag pairs. | Recheck 2026-11-21 of commit 1079cdf, which closed this row: the prefix index in `taxonomy_reports._indexed_positions` is exact (0 mismatches against the previous all-pairs scan over 7,050 seeded cases including thresholds 0, 1 and above 1, duplicates, empty names and 150-260 character names) but still calls `quick_ratio` for 57% of pairs on random 12-letter names (1,143,284 of 1,999,000 at 2,000 names; 0.14, 0.57, 2.43 s at 500, 1,000, 2,000), 31% on mixed lengths 3-20 and 27% on hyphenated word tags, so time still quadruples per doubling. `test_review28_53_equal_length_tags_skip_unrelated_pairs` uses names built from one unique character each, the index's best case. Opt-in report with no production caller. Next: add a realistic-alphabet scaling regression and either tighten candidate generation (for example positional or multi-token filters) or record the quadratic bound as accepted. |
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
| REVIEW28-58 | open | low | small | Docs/contract: a file placed in the documented transaction `stage` path without `capture()` aborts commit with a bare `KeyError`. | `source_transactions.py:116`; `docs/generator-composition.md:603-604` exposes `stage`. Reproduced: writing `manifest.json` into `tx.stage` raises `KeyError(PosixPath('manifest.json'))`; nothing is published. Next: capture on demand in `changes()` or raise a named error. |


## Translation authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-61 | open | low | small | Observability: the translator logs a retry and sleeps two seconds after the final attempt. | `translation_client.py:64-65,71`. Reproduced with `retries=0` and a refusing endpoint: one call, a 2 s sleep and a logged `retry 1` that never happens. Next: log and sleep only when another attempt remains. |


## Local preview

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-65 | open | low | small | Reliability: decisions in a class body nested in a function receive no complexity score. | `complexity_python.py:84-85,67-71`. Reproduced with Lizard 1.23.0: a function whose nested class body holds a filtered comprehension and a conditional expression scores 1. `docs/development.md:129-130` says unsupported syntax fails acceptance. Latent: no such code exists today. Next: keep class-body statements in the enclosing projection or reject decision nodes there. |
| REVIEW28-66 | open | low | small | Contradictions: `--root` does not relocate the default evidence path in the complexity CLIs. | `complexity_gate.py:220-221`, `complexity_xslt.py:206-207`: baseline, manifest and sources resolve against `--root`, the default `--report` against the working directory. Reproduced from another directory: `FileNotFoundError` for `reviews/complexity/functions.json` and `xslt.json`. Fails closed; CI runs from the repository root. Next: resolve a relative `--report` against the root. |
| REVIEW28-68 | blocked | low | small | Contradictions/wiring gap: the XSLT complexity inventory covers only the packaged stylesheet although AGENTS.md includes tests without exemptions. | `complexity_xslt.py:22,142-143` versus `complexity_gate.py:26-30` (tests are inventoried for Python and JS) and `docs/development.md:133`. The six `tests/fixtures/site/xsl/pages/*.xsl` files are in no inventory; `article.xsl` scores 10 for `match=/article` by `measure_template` and its top-level declarations are rejected by the gate parser. `reviews/complexity/xslt.md` scopes the metric to maintained packaged XSLT. Blocked on an owner decision: bring fixture XSLT into the inventory and baseline, or record the exclusion in AGENTS.md and the complexity guide. |


## Packaged content stylesheet

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Documentation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-72 | open | low | small | Contradictions: `TODO.md` does not fully follow its own legend or AGENTS.md. | The legend says effort `—` marks a retained `wont_fix`, yet REDOS-001 and REDOS-002 are `wont_fix` with efforts S and M; AGENTS.md requires a review category in each description or notes, and the eleven older `wont_fix` rows carry none. Does not reopen any decision. Next: label the rows and align the legend. |

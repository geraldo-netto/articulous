# TODO

Effort `—` means no change is planned for a retained `wont_fix` decision.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| PERF-33 | open | medium | medium | Reuse listing route calculation across sitemap and listing task planning. | Performance / data structure; after PERF-09, drive both consumers from one compatible pagination and route projection, without retaining page models across languages. Preserve complete sitemap scope and exact ordering under section/language/slug filters; count each needed listing route once and compare generated page and sitemap bytes. |
| PERF-34 | open | medium | medium | Bound plan-owned pending payload storage across eager sections. | Scalability; after PERF-11, consume generated RSS/sitemap/extra-page/extra-artifact task descriptors from scoped disk-backed plans or borrowed caller values. Account for caller-owned inputs separately; preserve section order, sitemap index-after-shard dependency, first-error settlement and workspace cleanup. Demonstrate bounded plan-owned payload growth before PERF-21 adds in-flight byte admission. |
| PERF-21 | open | medium | medium | Use byte-aware admission for queued render inputs and in-flight workers. | Scalability review; `runtime._drain_tasks` caps futures at twice the worker count, while `pipeline._TaskQueue.__iter__` materializes each task's full serialized input. On large pages, in-flight bytes and worker parser/serializer/native state have no independent budget. Measure peak RSS, scratch bytes and throughput with mixed input sizes. Preserve valid large worker values, allow isolated oversized tasks under an explicit policy, and verify all input borrows settle after error/cancellation. Validation 2026-11-21: confirmed (`runtime.py:225-227`, `pipeline.py:868-875`). `rss`/`sitemap`/`pages`/`artifacts` plan sections are fully built lists, and `LxmlEngine` thread-local compile caches grow with workers (88 compilations at 32 workers vs 7 at 1). Coupled with PERF-30 and PERF-11. Implementation: After PERF-11 and PERF-34, reserve byte and worker charges before decoding a descriptor and settle them once per completed/cancelled/failed borrow. State how projected output and native workspaces are funded. Exercise a single oversized task under an explicit budget rule, mixed sizes, producer failure and first-error drain. Compare against PERF-30 worker sizing. |
| PERF-08 | in_progress | low | small | Attribute the XSLT scaling plateau before changing worker topology. | Performance review; time queue decoding, XML parse, native transform, model projection, serializer, atomic writes and cache commits separately on the recorded morpha-portal workload. On a synthetic 403-page lxml build with 400 articles containing 200 paragraphs each, two runs at each of 1/4/8 threads took 1.036–1.069 / 1.061–1.066 / 1.113–1.135 s and produced identical path/content digests. One-worker totals across 403 outputs were 0.531–0.546 s CPU in serialization and 0.027–0.028 s CPU in native XSLT. Attribute the original workload independently. Compare 1/4/8 threads, CPU availability, and cold/warm filesystem conditions with byte-identical output. Identify phases that limit scaling and provide the baseline for PERF-07. Validation 2026-11-21: synthetic split reproduced: XSLT 0.044 s, `bytes(result)` 0.025 s, `html5_void_ends`+codec 0.507 s CPU. Over existing morpha-portal output, `html5_void_ends` alone took 2.77 s CPU (~28% of aggregate render CPU). Also time the Python model projection (`pipeline.py:840-848`), which morpha-portal uses. Re-baseline after PERF-14. Implementation: Collect a pinned baseline before source changes and repeat after REL-03/PERF-14 before evaluating PERF-32. Use isolated output directories and compare forced and warm output manifests at each thread count. Report phase CPU and wall separately and include the projection callback. Benchmark checkpoint: morpha-portal 71cde92 (360 articles, 1,409 HTML pages); 6 baseline and 6 optimized builds at 1/4/8 workers produced the same tree digest. Median one-worker HTML token CPU fell from 1.460 s to 0.021 s and total prepared wall time from 10.459 s to 8.601 s. Native XSLT still used 1.477 s CPU; Python projection used 0.158 s. Pending queue decoding, XML parsing, atomic output and cache publication timings. |
| PERF-32 | open | low | medium | Prototype a serializable built-in lxml worker boundary. | Performance / architecture; after PERF-08, transfer captured stylesheet and input values through an independent request/result contract. Keep composer callbacks on the existing thread path and keep the parent as sole output/cache writer. Differentially check returned bytes and typed failures, bounded IPC, worker death and quiescence before reclaiming private inputs. This is the evidence and contract prerequisite for PERF-07. |
| PERF-07 | open | low | large | Prototype bounded process workers and compare them with threads for XSLT rendering. The owner-requested morpha-portal baseline (1,397 pages, 356 articles) took 15.3 s / 14.0 s / 14.2 s overall at 1 / 4 / 8 workers; render took 5.5–6.2 s wall for about 10 s aggregate CPU. `runtime.run_parallel_tasks` uses threads; `pipeline._TaskQueue` serializes `_TransformSpec` and rebinds engine, context and shared cache when consuming it; `engines.LxmlEngine` compiles per thread at execution. | Performance / scalability / contradictions review. The prior row and morpha-portal's 2026-11-19 performance record attribute the plateau to GIL-bound XSLT. [lxml's threading contract](https://lxml.de/FAQ.html#threading) allows concurrent native transforms; the aggregate measurement does not locate the bottleneck. PERF-08 supplies attribution before implementation. If a process mode wins, have workers compile locally and return bounded results to the parent, which owns output writes and cache commits. Require byte-identical output, unchanged first-error settlement and atomic-output guarantees, thread fallback on unsupported platforms, per-function complexity evidence, configuration fuzzing if applicable, and measured end-to-end benefit with peak RSS and IPC cost. Validation 2026-11-21: code claims confirmed. The project registers no Python XSLT extension functions, and `read_file=False` blocks `document()`, so native transforms do not hold the GIL; a CPU-heavy transform scaled 3.0x at 4 threads. Synthetic evidence locates the GIL-bound cost in the Python serializer (PERF-14) and projection, contradicting `reviews/build-performance-2026-11-19/README.md:23`. `docs/model-projections.md:8` publicly states projections run on the thread pool, `_DeferredEngine`/`StylesheetCapture` must transfer to workers, and SaxonC already runs one process per page. Order REL-03, then PERF-14, then PERF-08, before this row. Implementation: Adoption depends on PERF-08, PERF-21 and PERF-32. Compare repeated end-to-end timings against the optimized thread path, including small-site crossover, IPC and resident memory. Keep caller projections and custom engine behavior on their documented executor boundary. Wire a bounded supported mode only if it wins with identical artifacts and contract-level lifetime/failure tests. |
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
| REL-40 | open | low | medium | Preserve later cache commits by other roots during delayed publication recovery. | Reliability/contradictions review; root isolation in `pipeline._load_build_cache` conflicts with `PosixPublicationBackend._rollback` restoring the entire prior shared cache. Reproduced with root B interrupted at installed, root A successfully refreshing activity from 2000000000 to 2000001000, then recovery of B reverting A to 2000000000. Durable ownership remains separate. Coordinate with PERF-17 and PERF-31. Add a failing regression that preserves A's later fingerprints/activity while restoring B's state, and keep byte-exact rollback when no other root committed. |
| PERF-31 | open | low | medium | Isolate fingerprint-cache I/O for the active output root. | Scalability / data structure review; `pipeline._load_build_cache` loads all output-root entries from the shared JSON under one lock and `_finalize_cache` rewrites all of them when one root changes. Measure time and peak memory against active versus inactive record counts. Preserve isolation, legacy admission, cache-loss recovery, ownership authority and coherent publication rollback, with explicit cross-root tests. Validation 2026-11-21: confirmed (`pipeline.py:1731-1740`, `1772-1774`). Other whole-file sites: `publication_adapter.publication_cache` (`publication_adapter.py:11-18`) and the `posix._begin` snapshot/rollback (`posix.py:110`, `203`). The shared cache lock serializes builds across roots. Preserve documented cache retention and see REL-40 for delayed cross-root recovery. Implementation: After PERF-17, specify one cache-store contract for incremental builds and publication/recovery, then measure root-keyed storage choices. Migrate under the existing shared lock after recovering pending journals, and preserve the public custom-backend cache_text contract through an explicit adapter/capability. Prove one active-root read/write independent of inactive record count. Preserve last-use metadata during migration; PERF-37 governs lock concurrency. |
| PERF-37 | open | low | medium | Narrow cross-root lock contention once cache mutations are root-local. | Performance / concurrency; after PERF-31, split the lock scope only when build, migration and recovery have a single lock order and cannot share mutable root state. Test parallel disjoint-root builds and recovery, serialization of the same root, and cross-root cache isolation under interruption. |
| REL-01 | wont_fix | low | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| PERF-29 | open | low | medium | Measure the remaining per-page SaxonC setup cost after PERF-28. | Performance review; `SaxonCEngine._do_transform` materializes XML, a stylesheet and protocol configuration and starts a separate supervised CLI process for each page, even at one captured template revision. Count startup, input setup and transform separately. Proceed to a bounded reusable native worker prototype only if measured gains justify it. Verify capability restrictions, process/descriptor lifetimes, output bytes, error isolation and cancellation settlement before adoption. Validation 2026-11-21: confirmed (`engines.py:471-528`): three temp workspaces and one `Transform` process per page. A bare `Transform` run is under 10 ms wall, so PERF-28 dominates today. A reusable worker needs the SaxonC API (no Python binding installed), must keep `-ext:off`, `-xi:off`, `allowedProtocols=#none`, and preserve the existing per-page failure/settlement boundary. Contradictions review: the earlier timeout claim conflicts with `backends/saxon.py:9-10` and `browser_process.observe_session`; 30 s is a progress checkpoint that resumes observation. Preserve progress reporting without a total runtime cap. Implementation: After PERF-28, report startup, private input materialization, transform and settlement separately. Use repeated equivalent output runs and hand the result to the PERF-35 go/no-go. |
| PERF-35 | open | low | medium | Evaluate reusable SaxonC workers at the measured setup crossover. | Performance / scalability; depends on PERF-29 evidence of a remaining repeatable setup bottleneck and availability of a SaxonC API with the existing execution restrictions. Prototype bounded supervised reuse only when both hold. Compare exact outputs, per-page error isolation and descriptor/private-input settlement with the CLI backend; keep the CLI as the supported path if the prototype fails the gate. |


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| PERF-17 | open | low | medium | Separate immutable recovery snapshots from publication phase transitions. | Scalability review; `PosixPublicationBackend._begin` base64-encodes the prior cache and ownership, and `_set_phase` serializes and writes both payloads with each of four phase records. Measure peak RSS and write volume on a large previous generation. Keep independently recoverable private copies, exact state restoration, changed-identity rejection and the existing phase/interruption acceptance tests. Validation 2026-11-21: confirmed: 4 phase records of ~16,976 B each for 12.5 KB of snapshots (~5.4x write volume). `cache_before` is the whole multi-root file, coupling with PERF-31 and REL-40. A new layout needs journal v2 while still recovering v1 journals (`posix.py:20-28`), durable snapshots with a journal digest before `prepared`, and single-hardlink validation before rollback. Implementation: For v2, prepare private streamed snapshots with validated digests and publish a compact prepared phase before mutation; subsequent phase writes carry only immutable claims. Recover v1 and v2, test every interruption/rollback boundary and measure bytes written. Feed this snapshot contract into PERF-31. |


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
| REDOS-001 | wont_fix | medium | S | Optional taxonomy matcher can retry quadratically on separator-leading names. | Security/performance review; taxonomy_completeness.py:31-44: tag `-a` produces an unanchored separator run followed by `a`; searching whitespace ending in `!` retries the run from each position. Local missing_tags cases at 1k/2k/4k characters took about 5/21/79 ms; no default build caller, only the opt-in public helper. Owner instruction 2026-10-24: stop content-focused analysis and let these findings go; no post code was executed. Declined for this pass; reconsider only on explicit owner resumption. Any future fix requires permanent failing-before/passing-after scaling/semantic controls, including literal punctuation and valid phrase boundaries. Evidence/scope: reviews/regex/README.md. |


## Browser code highlighting

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REDOS-002 | wont_fix | medium | M | Optional synchronous Prism highlighting has content-sensitive quadratic paths. | Security/performance review; code-blocks.js:29 calls highlightElement without a worker or admission bound. Packaged markup tag, Bash function and batch set-variable patterns show roughly 4x cost per doubled input in completed 1k–8k local text-only cases; no snippet was executed. Owner instruction 2026-10-24 declines further post-content/highlighting analysis and hardening. Keep disposition unless owner explicitly resumes. Future work must retain normal highlighting/copy behavior and permanent malformed-input/valid-boundary regressions, with owned cancellation if isolation is selected. Limited evidence and intentionally stopped vendor review: reviews/regex/README.md. |


## Browser search

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|

# TODO

Effort `—` means no change is planned for a retained `wont_fix` decision.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
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
| REVIEW27-20 | open | low | S | Reliability: ownership decoder limits bypass the restoration diagnostic. | load_ownership leaks a recursion or integer-limit exception. Preserve ownership bytes and report the file requiring restoration. |
| REVIEW27-01 | open | high | S | Correctness: Cache partition activation can strand a committed publication journal. | Interrupt journal removal in the retired directory during build_site with partition_cache enabled. Preserve the original cache identity until recovery succeeds and handle already-migrated retired journals. |
| REVIEW27-12 | open | medium | S | Correctness: Malformed pending journals can permit cache migration or abort a completed build. | _pending_journal treats a missing or non-string cache path as unrelated and leaks a decoder recursion error. Defer on unknown ownership and preserve the shared cache. |
| REL-01 | wont_fix | low | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-06 | open | medium | S | Correctness: Image maintenance silently omits unreadable subtrees. | image_optimization.candidates accepts an incomplete source inventory. Reject it before any conversion. |
| REVIEW27-14 | open | high | S | Correctness: A missing conversion result can install a previous image with the same basename. | A backend writes a result for a/photo.jpg but leaves no result for b/photo.jpg. Isolate each conversion result and preserve the second original. |


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-17 | open | high | S | Reliability: a failed process inventory can be mistaken for a settled browser session. | Deny listing /proc in owned_members. Propagate the failure so that an empty enumeration cannot authorize native cleanup. |


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-19 | open | low | S | Reliability: deeply nested journal JSON bypasses the recovery diagnostic. | recover_publication raises raw RecursionError. Preserve the journal and report its location and recovery instruction for decoder-limit failures. |
| REVIEW27-13 | open | high | S | Correctness: Publication accepts permissions changed after validation. | Change read permission on a staged asset, directory or root. Reject publication until the validated modes are restored. |


## Generated-site validation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-03 | open | low | S | Correctness: URL validation treats explicit port zero as the default port. | Compare an HTTP(S) reference at port 0 with a default-port base. Preserve distinct origins and accept an explicitly matching default port. |
| REVIEW27-04 | open | medium | S | Correctness: HTML validation omits unreadable subtrees. | read_pages silently skips an extra HTML page when its parent cannot be listed. Propagate the error before reporting validation success. |


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
| REVIEW27-09 | open | high | S | Correctness: An incomplete taxonomy selection can commit a partial corpus rewrite. | Deny directory enumeration for one language during apply_map. Propagate failure and preserve every original. |
| REDOS-001 | wont_fix | medium | S | Optional taxonomy matcher can retry quadratically on separator-leading names. | Security/performance review; taxonomy_completeness.py:31-44: tag `-a` produces an unanchored separator run followed by `a`; searching whitespace ending in `!` retries the run from each position. Local missing_tags cases at 1k/2k/4k characters took about 5/21/79 ms; no default build caller, only the opt-in public helper. Owner instruction 2026-10-24: stop content-focused analysis and let these findings go; no post code was executed. Declined for this pass; reconsider only on explicit owner resumption. Any future fix requires permanent failing-before/passing-after scaling/semantic controls, including literal punctuation and valid phrase boundaries. Evidence/scope: reviews/regex/README.md. |


## Browser code highlighting

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REDOS-002 | wont_fix | medium | M | Optional synchronous Prism highlighting has content-sensitive quadratic paths. | Security/performance review; code-blocks.js:29 calls highlightElement without a worker or admission bound. Packaged markup tag, Bash function and batch set-variable patterns show roughly 4x cost per doubled input in completed 1k–8k local text-only cases; no snippet was executed. Owner instruction 2026-10-24 declines further post-content/highlighting analysis and hardening. Keep disposition unless owner explicitly resumes. Future work must retain normal highlighting/copy behavior and permanent malformed-input/valid-boundary regressions, with owned cancellation if isolation is selected. Limited evidence and intentionally stopped vendor review: reviews/regex/README.md. |


## Browser search

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-15 | open | medium | S | Correctness: A search can invoke the renderer after its revision was reset during matching. | Reset from the match callback. End the stale search before creating a renderer container. |


## Source editing

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Translation authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-07 | open | low | S | Correctness: Variant discovery admits XML-named directories as translation files. | collect_variants includes a directory named folder.xml. Discover regular documents only. |
| REVIEW27-08 | open | medium | S | Correctness: Variant discovery treats an inaccessible language as empty. | collect_variants silently succeeds on a listing error. Distinguish an absent optional language from an unreadable one. |
| REVIEW27-11 | open | medium | S | Correctness: Deeply nested provider JSON bypasses translation error handling. | backends.translation_http propagates a decoder recursion error directly. Treat it as an invalid response and preserve retry and response cleanup. |


## Local preview

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW27-18 | open | low | S | Contradictions: the complexity guide lists four current exceptions while the checked measurement has three. | reviews/complexity/README.md lists parse_article_xml at 10. Its measured complexity is 6. Align the guide with functions.json and preserve the historical baseline. |
| REVIEW27-02 | open | medium | S | Correctness: The per-function executable-line gate rejects valid branch-enabled evidence. | coverage_gate compares the combined line/branch percentage to line counters. A loop with 3/3 measured lines and 1/2 branches must pass the individual line gate. |
| REVIEW27-05 | open | medium | S | Correctness: Output size reports silently omit unreadable subtrees. | output_metrics.scan returns partial byte totals on directory enumeration failure. Fail the scan and retain normal empty-tree behavior. |
| REVIEW27-10 | open | medium | S | Correctness: Complexity measurement can certify an incomplete source inventory. | Python/JS and XSLT measurement and verification use the same glob calls that swallow traversal errors. Fail if a maintained subtree cannot be enumerated. |
| REVIEW27-16 | open | low | S | Correctness: A region selector iterator only counts the first HTML page. | Scan two pages with a one-shot selector iterator. Report the region count and size across both pages. |

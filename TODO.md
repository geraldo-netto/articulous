# TODO

Effort `—` means no change is planned for a retained `wont_fix` decision.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-19 | open | high | S | Correctness: cancellation raised inside an executing task is reported as a successful build step. | In `runtime._collect_one`, a submitted callable raising concurrent.futures.CancelledError makes `run_parallel_tasks` return an empty result without failure. With a cancelled native search writer the build returned success and recorded the missing search.json as owned. Distinguish failed running work from executor-cancelled pending futures. Verify failure propagation, sibling settlement and prevention of successful output finalization. |
| AUDIT26-20 | open | low | S | API consistency: the public executor coerces unsupported worker counts. | `runtime.run_parallel_tasks` documents a positive integer or auto, yet accepts True, the string 2, and 1.5, truncating the float. Match configuration admission and verify invalid types are rejected before task execution while valid integers and auto still work. |
| PERF-01 | wont_fix | low | — | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | low | — | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| DUP-01 | wont_fix | low | — | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| UNUSED-02 | wont_fix | low | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | low | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | low | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |


## Article discovery and models

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-25 | open | high | S | Reliability: a transient read failure can retract a published article and remove its feed and listing entries. | Build the fixture, change first-post.xml to mode 000 as its non-root owner, then rebuild. The CLI succeeds and deletes the existing article page. `articles.parse_article_xml` handles operational read errors like invalid XML. Fail the build before output mutation on inaccessible inputs, with separate controls for malformed XML and intentionally deleted sources. |
| AUDIT26-08 | open | high | S | Correctness: a filtered build can leave nonreciprocal translation links after cache loss. | Build an English/French translation pair, remove the English group marker, delete the cache and rebuild English only. English drops its alternate while French still links to English. In `translations.TranslationStore.validate_filters`, preserve enough durable peer information or require a full build when prior relationships cannot be established. Verify rejection before writes and repair by a full build. |
| SCAL-01 | wont_fix | low | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | low | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| REL-02 | wont_fix | low | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |


## Cache persistence

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-01 | open | high | M | Correctness: switching back to an older fingerprint cache can leave stale published pages. | In the fixture, build article text A with the default cache, change to B with a second cache, then restore A and the default cache. The third build succeeds with B still on disk. In `pipeline._load_build_cache` and `runtime.should_rebuild`, bind skip decisions to the current output generation. Require byte equality with a fresh A build across cache switches and restored backups, including partial builds. |
| AUDIT26-04 | open | medium | S | Reliability: some unreadable JSON values abort builds using a disposable cache. | `runtime.load_cache` falls back on JSONDecodeError, but 1,200 nested arrays raise RecursionError and a 5,000-digit integer raises ValueError on CPython 3.11. Exercise both through a fixture rebuild with valid ownership and verify fresh fingerprints and correct output while preserving special-file rejection. |
| REL-01 | wont_fix | low | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-02 | open | high | S | Correctness: an unreadable asset source directory is treated as empty and its published children are pruned. | Build with `assets/sub/keep.txt`, change the source directory to mode 0111 as its non-root owner and rebuild. The CLI succeeds and removes the published file. Make `pipeline._asset_manifest` propagate an incomplete traversal before any mirror mutation. Cover incremental and prepared builds and the genuinely empty-directory control. |
| AUDIT26-16 | open | medium | S | Correctness: incremental assets retain old permission bits after a source chmod. | Build a mode-0600 stylesheet, change it to 0644 without changing its content, then rebuild: the mirrored file remains 0600 until forced. `pipeline._asset_manifest` omits the mode copied by `filesystem.copy_asset_file`. Verify both permission tightening and loosening produce the same result as a fresh mirror, including pre-change caches. |


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-22 | open | medium | S | Scalability: browser shutdown cannot wait on valid high-numbered process descriptors. | `backends.browser_fence.await_members` uses select.select. A ready pidfd for an exited child, duplicated to descriptor 1024, raises ValueError on Linux even with just one entry. Use a polling primitive supporting high descriptors and verify ready, pending, timeout and cleanup behavior with an owned child pidfd. |
| AUDIT26-15 | open | medium | S | Contradictions: malformed metadata can block acquisition of an unheld build lock. | `docs/output.md` promises recovery of malformed lock metadata. A lock file containing 1,200 nested JSON arrays raises RecursionError in `filesystem._stale_lock_reason` after flock succeeds. Exercise recovery and metadata refresh under a free lock while preserving live contention handling. |


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-26 | open | high | S | Correctness: a validated generation can publish content added after validation. | Render and validate a fixture with an empty asset directory. Add a file there, make the directory execute-only and publish. Both `assert_unchanged` and `publish_validated` succeed and the extra file becomes live. `filesystem.tree_fingerprint` must reject incomplete enumeration. Verify failure before publication and success for an unchanged readable stage. |
| AUDIT26-23 | open | high | M | Recovery: interrupted or failed journal cleanup can make a committed publication unrecoverable automatically. | In the AUDIT26-03 fixture, recursive deletion in `backends.posix._cleanup` removed journal.json before failing on previous/en/articles. After restoring permissions, recovery still rejected the transaction for its missing journal. Make retirement retryable after each cleanup boundary and verify a later recovery preserves the committed generation. This fault can also occur independently of output admission. |
| AUDIT26-14 | open | high | S | Recovery: incremental output writes can prevent recovery of an interrupted whole-site publication. | Stop the publisher at the existing old_moved test checkpoint, then run the standard build. It succeeds and creates a new output directory. `recover_publication` then rejects the new identity. Under the output lock, prevent incremental mutation while the destination transaction exists. Verify the recovery succeeds after rejection, across the supported journal phases. |
| AUDIT26-03 | open | high | S | Ownership: whole-site publication admits an incompletely inspected destination. | Add an unowned file inside an otherwise owned output directory and change the parent to mode 0111. `ownership.validate_owned_output` returns success because rglob skips its contents. A real build_site committed the replacement, removing the manual file from the live tree. Abort publication before moving the destination when any directory cannot be enumerated. Verify preservation of the old generation, manual file, cache and ownership. |


## Generated-site validation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-10 | open | medium | S | Correctness: invalid sitemap XML can pass publication validation. | `site_validation.sitemap_document` selects every descendant named loc by local name. A urlset in an unrelated namespace with its only loc under nonsense passes `validate_site` for the expected URL. Check protocol element names, namespaces and direct url/sitemap entry structure. Exercise valid namespaced indexes and shards plus misplaced and foreign elements. |
| AUDIT26-05 | open | medium | S | Correctness: canonical detection includes inert template links and ignores active case variants or multi-token rel values. | `site_validation.page_references` returns only /fake for an active `rel="CANONICAL"` pointing to /correct plus a template containing `rel="canonical"` pointing to /fake. Match the canonical relation as an ASCII case-insensitive token outside templates. Verify valid, missing and duplicate active links through page validation. |


## Sitemap generation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Configuration

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-09 | open | medium | S | Contradictions: the CLI writes missing configuration into output before enforcing the output exclusion. | From a fixture run `--dry-run --config output/missing.json`. `cli.main` exits with the documented exclusion error after `config.load_or_create_config` creates both paths. Admit the default layout before writing a missing file. Cover rejection without side effects and creation at an allowed location. |
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
| AUDIT26-11 | open | medium | S | Concurrency: synchronous reentry into search starts two index loads and can cache the stale response. | In `search-client.js:loadEntries`, have the first loader synchronously invoke a second search before returning its promise. Two loads start. Resolve the second then the first: the next query renders the first load’s stale rows. Reserve the shared request before calling the loader, preserving synchronous admission, retry, reset and disposal contracts. |


## Source editing

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-12 | open | medium | S | Reliability: publishing an incompletely readable stage silently omits a requested source edit. | Use `source_transaction.write` for sub/file, then make its staged parent execute-only. `SourceTransaction.changes` skips the entry and the context returns without installing the file. Abort before publication when the stage cannot be enumerated. Cover a multi-file batch, unchanged destinations and workspace cleanup reporting. |


## Translation authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-18 | open | high | S | Data integrity: the XML translation adapter can overwrite its own original. | Passing the same path as source and target to `translation_xml.mirror_xml` replaces the original with translated text and generated provenance. Reject a target that names the original before translation or publication. Verify unchanged original bytes, no provider calls and correct handling of distinct paths. |
| AUDIT26-24 | open | medium | S | Correctness: a translation rejected by the XML decoder is cached as a success and prevents retry. | Translate a paragraph containing sibling bold and italic elements. Have the provider return balanced numbered placeholders with the second inside the first. Both mirror attempts retain the source and report failure, but the second hits the cache and never requests the available corrected translation. Coordinate `Translator` cache admission with `translation_xml.translate_blocks` structural validation. Verify existing bad cache entries can be evicted and repaired. |
| AUDIT26-17 | open | medium | S | Correctness: translating an article that relies on its default language can emit a translation classified in that original language. | With `XmlTranslationLayout.language_element="lang"`, translate an English article lacking lang into French. `mirror_xml` writes successful provenance, but `parse_article_xml` still reports en. Materialize the configured target-language element on the mirror. Cover absent, present and explicitly disabled language fields. |


## Local preview

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-13 | open | low | S | Contradictions: the documented plain preview fallback is labelled HTML. | With `--not-found /missing-404.html` and no such file, a loopback GET returns the built-in plain body with Content-Type text/html. In `preview.Handler.not_found`, derive the type from the body actually selected. Verify GET/HEAD headers and the successful custom HTML case. |


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| AUDIT26-21 | open | medium | S | Contradictions: the coverage gate can accept counters from a different implementation of the same function. | `docs/development.md` says stale counters are rejected. Measure a two-line f returning 1, replace its body with a raise on the same line and recheck the original native JSON: `coverage_gate.check_report` still returns one function and no errors. Bind verification evidence to measured source content and regress same-line edits using native coverage. |
| AUDIT26-07 | open | medium | S | Verification: a missing requested coverage directory passes the per-function gate. | `coverage_gate.check_report` returns zero functions and no errors for a nonexistent directory, so a typo or missing source tree can pass CI. Fail explicitly on missing or non-directory inventory roots and cover both a typo and a valid measured package through the command. |
| AUDIT26-06 | open | low | S | Observability: the size report gives the lower middle page as the median for an even sample. | `output_metrics.overall` reports 1 KB for pages of 1 and 9 KiB. Compute both central observations for even counts, retain odd/empty behavior and verify the displayed 5 KiB median. |

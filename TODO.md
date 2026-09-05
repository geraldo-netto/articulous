# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-09 | open | M | Validate discovered article entries before opening them (`articulous/articles.py:218`, `articulous/articles.py:271`). | High. A content-file symlink published an XML article from outside the project, including its private description. A FIFO named `pipe.xml` blocked the build until an isolated one-second timeout killed it. Reject source symlinks/special files or enforce an explicit confined-link policy before parsing. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCAL-05 | open | M | Stream article-file discovery instead of sorting the entire recursive result in memory (`articulous/articles.py:271`, `articulous/articles.py:297`). | Medium. A synthetic 20,000-path walk is fully consumed and retained before the first article is parsed. Preserve deterministic traversal with bounded buffering; the current single-article memory claim excludes this global path list. |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DATA-04 | open | M | Reject build-state paths that alias project inputs (`articulous/config.py:180`, `articulous/pipeline.py:1357`). | High. Accepted `build.cache_file="config.json"` causes a successful build to overwrite configuration with cache keys; next startup fails schema validation. Validate cache/config ownership before writes, including configured aliases. |
| DATA-05 | open | M | Preserve complete shared feeds and listing pages during language/slug-filtered builds (`articulous/pipeline.py:1075`, `articulous/pipeline.py:1092`, `articulous/pipeline.py:1174`). | Medium. After a full three-article build, `--slug first-post` rewrites global search with one article while other pages remain published; shared RSS, sitemap, index and tag inputs use the same filter. Aggregate complete published inputs for shared outputs, or explicitly exclude shared outputs from targeted updates. |
| DATA-06 | open | M | Bind cached output ownership to the resolved output tree and coordinate shared cache writes (`articulous/pipeline.py:1344`, `articulous/pipeline.py:1363`, `articulous/pipeline.py:1494`). | High. Build output A, then output B with a different article URL pattern but the same cache; mark an article private and rebuild A. Its old public page survives because B replaced A's manifest. Namespace or isolate cache state per output; separate output locks currently also permit concurrent writes to the same cache file. |

## system design

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## code duplication

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## architecture/modularity/SOLID

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## decoupling

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## reliability/correctness

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REL-22 | open | M | Reconcile actual asset destination types instead of relying only on cached source types (`articulous/pipeline.py:258`, `articulous/pipeline.py:266`). | Medium. Replace a previously copied `output/assets/style.css` file with a directory; the next build succeeds but writes `style.css/style.css`. Compare destination metadata before copying and handle file/directory drift. |
| REL-23 | open | M | Include retained output owners in partial-build collision preflight (`articulous/pipeline.py:1243`, `articulous/pipeline.py:1344`). | High. Following a full build, set `urls.rss` to an existing article's `index.html` and run `--only rss`: the article is overwritten and the saved manifest assigns both keys the same path. Validate planned outputs against all unselected owners before publishing. |
| REL-24 | open | S | Validate cached asset metadata before indexing its fields (`articulous/pipeline.py:209`, `articulous/pipeline.py:250`, `articulous/pipeline.py:258`). | Medium. Cache entry `{"assets":{"version":1,"manifest":{"style.css":null}}}` reaches `old[rel][0]` and aborts with `TypeError`; malformed list shapes also need handling. Discard invalid asset cache entries and rebuild the mirror. |
| REL-25 | open | M | Protect current mirrored assets when pruning legacy generated-output paths (`articulous/pipeline.py:1451`, `articulous/pipeline.py:1511`). | Medium. A cached RSS owner at `assets/style.css` is accepted; migrating RSS to its default path copies the current asset, then deletes it during prune. Include current asset ownership in pruning protection and validate legacy paths against the reserved subtree. |
| REL-26 | open | S | Handle UTC conversion overflow for article dates and scheduled publication timestamps (`articulous/articles.py:103`, `articulous/articles.py:140`, `articulous/articles.py:234`). | Medium. `0001-01-01T00:00:00+01:00` raises uncaught `OverflowError` in either field, aborting the scan instead of rejecting the article or keeping it scheduled. Add both timezone/year boundaries to parser regressions. |
| REL-27 | open | M | Close projection stores and sinks when the initial article stream fails (`articulous/pipeline.py:1092`, `articulous/pipeline.py:1243`). | Medium. A stream yielding one article then raising `OSError` leaves four descriptors open after workspace cleanup while the exception is retained. Projection creation occurs outside the cleanup-protected collection block; close resources inside the failing streaming scope. |
| REL-28 | open | S | Clean Saxon input temporaries if materialization fails before the transform starts (`articulous/engines.py:256`). | Low. Injected `OSError` from the initial temporary-file write leaves its `delete=False` XML file on disk; cleanup starts only after that write. Establish cleanup ownership immediately after allocation and cover write/close failures. |
| REL-29 | open | M | Validate URL-pattern syntax separately from filesystem output shape (`articulous/sections.py:71`, `articulous/sections.py:88`, `articulous/models.py:104`). | Medium. Accepted RSS patterns `/feed.xml?format=rss` and `/feed.xml#section` produce literal filenames containing query/fragment text, while clients request `/feed.xml`. Encoded path segments are likewise copied verbatim. Reject unsupported URL components or map decoded output paths and encoded URLs consistently. |
| REL-30 | open | S | Give projection tests explicit workspace ownership and cleanup (`tests/test_pipeline.py:1078`, `tests/test_fuzz_edges.py:202`, `articulous/pipeline.py:1108`). | Low. Running only `test_stream_projections_collects_all_and_bounds_rss` with an isolated `TMPDIR` leaves two projection data files (610 bytes) after pytest exits. Tests that let helpers create an implicit `TempWorkspace` never unlink its `delete=False` files; use a managed workspace fixture and close stores/sinks. |
| REL-31 | open | S | Reject an existing non-directory asset source before reconciling the mirror (`articulous/pipeline.py:179`, `articulous/pipeline.py:294`). | Medium. After a successful build, replacing the source `assets` directory with a regular file causes the next build to succeed and delete the published stylesheet: recursive discovery treats the file as an empty tree. Distinguish an intentionally missing optional directory from an invalid existing source. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-05 | open | M | Collect running-task errors when the task producer fails (`articulous/runtime.py:223-234`). | Medium. With a worker raising `RuntimeError` and the producer raising `ValueError`, the executor waits for the worker but neither logs nor aggregates its failure. Drain pending futures through the result collector on producer/submission failure, preserving the original error and any worker diagnostics. |

## wiring gaps

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

---

## Open — parked

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-01 | parked | S | `_stream_projections` emits no per-section progress; only final tally/plan logs are emitted (articulous/pipeline.py:838-874; articulous/pipeline.py:923-941) | Deliberate to keep production logs quiet; revisit if very large sites need progress feedback. |
| OBS-02 | parked | S | `timed()` wraps tasks at DEBUG only; production builds see no per-task signal (articulous/runtime.py:144-152) | Same trade-off as OBS-01; bumping to INFO would flood logs for normal builds. |
| DOC-01 | parked | S | `SiteModelCtx` `@property` members carry no docstrings (articulous/models.py:25-47) | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |

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
| DOC-03 | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

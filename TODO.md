# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DATA-07 | open | M | Preserve output ownership when the build cache is removed or invalid (`articulous/pipeline.py:1375`, `articulous/pipeline.py:1449`). | High. Full build, mark `first-post` private, delete `.build-cache.json`, rebuild: its public HTML survives because the only pruning manifest disappeared. Keep durable ownership separately, or require an explicit clean-output recovery. |
| DATA-08 | open | M | Retain ownership of files published before a later build failure (`articulous/pipeline.py:1573`, `articulous/pipeline.py:1576`). | High. On a fresh site, execute article tasks then raise from a later section; no manifest is saved. Mark a rendered article private and retry successfully: its public page remains orphaned. Journal planned/published ownership or stage publication transactionally so failed builds remain recoverable. |
| DATA-09 | open | S | Protect the active configuration from generated output paths (`articulous/config.py:269`, `articulous/pipeline.py:763`). | High. Use `--config output/search.json` with valid site configuration at that path: a successful build replaces it with the search array, breaking the next startup. State-path alias checks do not protect configuration from page writers. Reject configuration inside the output tree before publishing. |
| DATA-10 | open | M | Prune stale generated paths without following symlinks to unowned files (`articulous/pipeline.py:1477`, `articulous/pipeline.py:1523`). | High. After a full build, replace an article's `index.html` with a symlink to untracked `output/manual.txt`, then make the article private. Pruning deletes `manual.txt` and leaves the broken link. Remove or reject the stale link itself; validate ancestor links without treating their targets as owned. |

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
| REL-32 | open | S | Reject special files before opening configuration, cache or log paths (`articulous/config.py:229`, `articulous/config.py:257`, `articulous/runtime.py:91`, `articulous/cli.py:132`). | Medium. A FIFO at any of these paths blocks the CLI indefinitely; each isolated reproduction exceeded a two-second timeout. Existing state validation rejects aliases and hardlinks but accepts FIFOs. Check opened file types without blocking and fail clearly. |
| REL-33 | open | S | Validate the asset mirror root before taking the unchanged fast path (`articulous/pipeline.py:338`). | Medium. Build with an empty assets directory, replace `output/assets` with a regular file, rebuild: the file remains because both manifests and the mismatch set are empty. Require a directory destination before skipping copy/type repair; add the empty-tree regression. |
| REL-36 | open | M | Check derived slug/path lengths before any build output is published (`articulous/articles.py:246`, `articulous/pipeline.py:886`, `tests/test_fuzz_edges.py:148`). | Medium. A valid article with a 260-character ASCII title parses successfully, then its worker raises `ENAMETOOLONG`; other tasks may already have published. Preserve the parser's unrestricted-string contract but reject oversized output components during build preflight. Extend the existing oversized-title parser test through the build pipeline. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

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
| OBS-01 | parked | S | `_stream_projections` emits no per-section progress; only final tally/plan logs are emitted (articulous/pipeline.py:1114; articulous/pipeline.py:1206) | Deliberate to keep production logs quiet; revisit if very large sites need progress feedback. |
| OBS-02 | parked | S | `timed()` wraps tasks at DEBUG only; production builds see no per-task signal (articulous/runtime.py:145) | Same trade-off as OBS-01; bumping to INFO would flood logs for normal builds. |
| DOC-01 | parked | S | `SiteModelCtx` `@property` members carry no docstrings (articulous/models.py:34) | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |

## Audit picks deliberately rejected

| id | description | reason |
|----|-------------|--------|
| PERF-01 | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| SCAL-01 | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| DUP-01 | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| REL-01 | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |
| REL-02 | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |
| UNUSED-01 | `deep_merge` (articulous/config.py:57) used only by `load_or_create_config` | Internal helper with direct unit tests; keep. |
| UNUSED-02 | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

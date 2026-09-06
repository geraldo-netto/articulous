# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## contradictions

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CONTR-02 | blocked | S | Reconcile response-format instructions for repository work. | `AGENTS.md`, Communications requires headings and bullets; the current session's developer Writing style instruction says to avoid section headings and use lists selectively. The developer instruction takes precedence for this scan. Impact: both formatting requirements cannot be followed together; resolve by making the repository rule compatible with the session override. |

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
| REL-04 | open | M | [P2] Handle owned file-to-directory route migrations during planning and publication. | `articulous/pipeline.py:1639-1645` publishes before pruning obsolete owned files. After a fixture build, changing RSS from `/rss.xml` to `/rss.xml/feed.xml` passes `--only rss --dry-run` but live planning/publication fails with `NotADirectoryError`; the old owned file blocks its replacement directory on every retry. Plan safe removal of selected owned obstructions, preserve unowned/retained paths, and cover both migration directions and dry-run diagnostics. |
| REL-06 | open | M | [P2] Exercise the advertised SaxonC backend with a real executable in integration tests. | `tests/test_engines.py:432-568` and `tests/test_article_snapshots.py:127-151` mock the subprocess for successful transforms; `.github/workflows/main.yml` installs only the Python test dependencies. No real `Transform` executable was available for this scan. Command construction has coverage, but actual rendering, accepted CLI switches, external-resource restrictions, and nonzero-exit behavior are not verified against SaxonC. Add a pinned backend integration job with successful fixture output and resource-denial checks; retain the fast mocked unit tests. |

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

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
| SEO-08 | open | L | Split oversized native sitemaps and generate a sitemap index. | P2. `articulous/pipeline.py:_write_native_sitemap` currently rejects output beyond 50,000 URLs or 50 MiB; retain those safeguards per shard. Accept: deterministic shards, bounded memory, an index referencing every shard, ownership/pruning of retired shards, and recovery after interrupted publication. Test exact URL/byte limits, one-over cases, multibyte content, and shrinking builds. [Sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap). |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEO-04 | open | M | Add an explicit search-indexing policy independent of publication/listing status. | P1. `articulous/articles.py:PublicationPolicy` controls generated pages and discovery feeds but exposes no indexing directive; `unlisted` only removes discovery links. Preserve and document that existing default, with an explicit noindex option passed through SEO-01 to reference templates. Accept: noindex pages remain crawlable, leave the sitemap, and rebuild when the directive changes; private/draft pages remain unpublished. Add reproducible invalid/duplicate-field fuzz cases and valid defaults. [Indexing controls](https://developers.google.com/search/docs/fundamentals/get-started-developers). |

## system design

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEO-05 | open | M | Provide robots.txt delivery with sitemap discovery and deployment documentation. | P1. `articulous/sections.py:SECTION_SPECS` has no robots output; `articulous/pipeline.py:copy_assets` places files under `/assets/`. Accept: a supported route to host-root `/robots.txt` containing the absolute sitemap/index URL, with explicit host-root deployment instructions for sites served below a base path. Preserve crawl access to public assets and noindex pages; cover dry runs, ownership/collisions, and reproducible invalid URL/rule fuzz cases with valid boundaries. [Robots placement](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt). |
| SEO-06 | open | L | Model translation relationships and render reciprocal hreflang annotations. | P2. `articulous/articles.py:Article` records language but no relationship between translated articles. Accept: an explicit translation identifier, self-inclusive reciprocal alternate links for actual indexable translations, absolute URLs from configured patterns, and no inferred equivalence from titles/slugs. Map supported locale spellings such as `en_US` to valid annotation codes without changing existing routes; cover missing/private translations, filtered builds, cache invalidation, and reproducible invalid/duplicate-ID and locale fuzz cases. Depends on SEO-01/04. [Localized pages](https://developers.google.com/search/docs/specialty/international/localized-versions). |
| SEO-10 | open | M | Add an optional Article/BlogPosting structured-data example. | P3. `tests/fixtures/site/xsl/pages/article.xsl` has no structured data; parsed metadata lacks dedicated author, image, and modification fields. Document optional source metadata and render JSON-LD matching visible content, omitting unavailable values. Accept: parseable, safely escaped JSON-LD using SEO-01's canonical URL, accurate publication/modification dates, and a documented Rich Results Test check. Add reproducible malformed-field and script-termination fuzz cases plus valid Unicode/optional-field cases for any new input contract. [Article guidance](https://developers.google.com/search/docs/appearance/structured-data/article). |

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
| SEO-02 | open | M | Add SEO head markup to the reference HTML templates and document the template contract. | P1. `tests/fixtures/site/xsl/pages/article.xsl` only renders a title in its head; `index.xsl` and `tags.xsl` have no head. These are test fixtures, not production themes. Accept: meaningful titles, description metadata when available, resolved HTML language, and one absolute self-canonical per page, using SEO-01 for articles and existing `@self` for listings. Keep each pagination page self-canonical; preserve relative-only builds by omitting unavailable absolute canonicals. Verify rendered fixture HTML and custom base paths. [Canonical guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls). |
| SEO-03 | open | M | Expose pagination URLs and render crawlable links between index pages. | P1. `articulous/models.py:IndexPage` and `articulous/pipeline.py:_index_doc` expose page counts but no adjacent URLs; the reference `index.xsl` only links articles. Accept: normal anchor links connecting the full sequence using configured URL patterns, with first/last/single-page handling and no out-of-range destinations. Verify all pages are reachable from page one with custom patterns and deployment prefixes. [Pagination guidance](https://developers.google.com/search/docs/specialty/ecommerce/pagination-and-incremental-page-loading). |
| SEO-07 | open | M | Extend sitemap entries with trustworthy modification dates and optional index/tag coverage. | P2. `articulous/pipeline.py:SitemapSink` stores URL strings, `_add_cross_projection` only adds articles, and `_write_native_sitemap` only emits loc. Accept: an optional validated content-modified field, lastmod omitted when unknown rather than set to build time, and configurable inclusion of indexable listing pages. Preserve publication exclusions and complete global sitemap scope during filtered builds; update native and documented XSLT inputs consistently. Test cache invalidation, encoded URLs, and reproducible invalid/duplicate/date-boundary fuzz cases. [Sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap). |
| SEO-09 | open | M | Support explicit stable article slugs and document URL-change redirects. | P2. `articulous/articles.py:parse_article_xml` derives each slug from the current title or filename, so a title edit changes its public URL. Accept: an optional validated slug retaining legacy fallback, with title edits preserving explicitly chosen URLs across HTML, links, feeds, and sitemap. Add reproducible invalid/duplicate/path-traversal and collision fuzz cases with valid boundary slugs. Document permanent redirects at the deployment layer for intentional URL changes and verify existing pruning behavior remains intact. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## wiring gaps

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEO-01 | open | M | Pass resolved article SEO metadata into the actual XSLT rendering path. | P1; prerequisite for SEO-02/04/06/10. `articulous/articles.py:Article` already has the resolved URL and language, but `articulous/pipeline.py:build_articles_section` transforms only captured source XML; unlike listing `@self`, generated article URLs are unavailable to templates. Accept: a documented metadata/parameter contract for URL, resolved language, and site name in both lxml and SaxonC, preserving snapshot/base-URI semantics. Include values in fingerprints and test metadata-only config changes, language fallback, custom URL patterns, and production dispatcher invocation. |

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

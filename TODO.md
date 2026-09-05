# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## contradictions

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CONTRA-01 | blocked | S | Reconcile conflicting TODO formats in [AGENTS.md](AGENTS.md) and the [todo-ledger skill](/home/netto/.codex/skills/todo-ledger/SKILL.md). | Repository rules require category tables with `id`, `status`, `effort`, `description`, `notes`; the skill requires exactly three lifecycle tables with `id`, `status`, `severity`, `effort`, `description`. Applying the skill literally would discard the required repository structure. User-provided repository instructions take precedence. Unblock by aligning the skill and repository guidance on a compatible format, then verifying both. |
| CONTRA-02 | blocked | M | Reconcile the asset-mirror removal guarantee with cache-dependent deletion history. | High; README.md:333 promises removed source entries are pruned, but articulous/pipeline.py:272,289 only remove entries remembered by the fingerprint cache; the persistent ownership manifest excludes assets. Reproduced: build `assets/retired.txt`, delete the source and cache, rebuild; the public copy survives. The same leak follows a failed first build after asset copying and a full recovery. Unblock by defining durable asset ownership/reconciliation, implementing it, and testing cache loss plus failed-build recovery against the documented mirror contract. |
| CONTRA-03 | blocked | S | Update the targeted-pruning documentation to agree with persistent ownership. | Low; README.md:139 says pruning requires ownership in the cache, while README.md:74-82 and articulous/pipeline.py:1563 use the independent ownership sidecar and preserve pruning after cache loss. The stale condition misleads recovery and targeted-build guidance. Unblock by documenting sidecar ownership and legacy cache migration consistently, then verifying the stated behavior. |
| CONTRA-04 | blocked | M | Reconcile private-article exclusion with reopening mutable source XML after publication policy checks. | High; README.md:133 excludes private content, but articulous/pipeline.py:1151 checks parsed metadata, articulous/pipeline.py:781,876 hash/queue a path, and articulous/engines.py:213 later parses that path again. Reproduced: change an article to `private` and replace its description after planning but before workers run; the build succeeds and publishes the new private description. Unblock by choosing a consistent input snapshot or fail-on-change policy, sharing the validated bytes with rendering/fingerprinting, and verifying concurrent edits cannot publish unchecked content. |
| CONTRA-05 | blocked | M | Define and enforce handling of contradictory singleton XML fields. | High; articulous/articles.py:110 silently keeps the last title/date/language/status, while the shipped article stylesheet selects the first title (tests/fixtures/site/xsl/pages/article.xsl:7). Reproduced: two different titles produce one title on the article page and another in its slug/search entry; `<status>private</status><status>published</status>` silently publishes the article despite the conflicting privacy declaration. Unblock by defining an explicit duplicate-field policy, rejecting conflicting declarations before publication, and verifying consistent page/listing metadata plus fail-closed status handling. |
| CONTRA-06 | blocked | S | Make dry-run asset-path validation agree with normal-build validation and its documentation. | Medium; README.md:231-234 says dry runs validate paths, but articulous/pipeline.py:335 returns before validating asset destination entries. Reproduced: replace `output/assets/style.css` with a symlink; dry run succeeds, while the identical normal build raises `Asset destination contains a symlink`. Unblock by running nonmutating destination/cache-path validation in both modes and testing matching failures without publication. |
| CONTRA-07 | blocked | M | Reconcile relative-URL support with the native sitemap's standard-format guarantee. | Medium; README.md:280-282 describes native standard formats, but articulous/config.py:165 accepts an empty `site.base_url`, tests/test_fuzz_edges.py:170 explicitly permits relative URLs, and articulous/pipeline.py:673 emits them unchanged in sitemap `<loc>` entries. Reproduced: full fixture build with an empty base URL succeeds with `/en/articles/first-post/` in the native sitemap. The [Sitemaps protocol](https://www.sitemaps.org/protocol.html) requires URLs beginning with a protocol. Unblock by defining sitemap behavior for relative-only sites, validating absolute sitemap URLs before publication, and preserving intentional relative links elsewhere. |
| CONTRA-08 | blocked | S | Align the integration site's RSS and sitemap fixtures with the formats they claim to generate. | Low; tests/fixtures/site/xsl/pages/rss.xsl:6 emits RSS 2.0 without channel `title`, `link`, or `description`, required by the [RSS specification](https://www.rssboard.org/rss-specification); tests/fixtures/site/xsl/pages/sitemap.xsl:6 omits the [required sitemap namespace](https://www.sitemaps.org/protocol.html). Reproduced both outputs with the fixture build, selecting lxml for sitemap; current smoke tests still pass because they mostly check file existence. Unblock by making the fixture formats valid and adding structural format assertions for the actual rendered feeds, including the XSLT sitemap backend. |
| CONTRA-09 | blocked | M | Use the same stylesheet base URI for dependency fingerprinting and lxml compilation. | Medium; articulous/engines.py:87 resolves a stylesheet symlink and hashes includes relative to the physical target, while articulous/engines.py:201 parses the original path and resolves includes relative to the link. Reproduced: `pages/article.xsl` links to `templates/article.xsl`, both directories contain different `common.xsl` files, and the stylesheet includes `common.xsl`; hashing tracks `templates/common.xsl`, rendering uses `pages/common.xsl`, and editing the rendered dependency leaves the fingerprint unchanged and output stale. Unblock by choosing one base-URI policy for both stages and testing symlinked roots/dependencies plus `xml:base`. |

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
| CONC-04 | open | M | Bind stylesheet fingerprints to the exact stylesheet/dependency bytes used by workers. | High; articulous/pipeline.py:862 hashes stylesheets during planning, but articulous/engines.py:201 recompiles their mutable paths later under the old fingerprint. Reproduced: change article.xsl after planning, let workers publish, restore the original stylesheet, then rebuild; the unchanged-input build incorrectly retains the intermediate stylesheet output. Snapshot the dependency graph or reject changes before committing outputs/cache, and test edits plus reverts. Reuse the input-consistency approach chosen for CONTRA-04, URI policy from CONTRA-09, and safe readers from REL-39. |

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
| REL-37 | open | S | Deduplicate an article's repeated tag memberships before building tag pages. | Medium; articulous/models.py:161 appends the same article for every occurrence in `art.tags`. Reproduced: two `<tag>intro</tag>` fields yield two identical article links on the intro page. Preserve tag order while deduplicating membership; test repeated tags alongside distinct articles sharing a tag. |

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

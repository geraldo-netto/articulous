# TODO

Effort `—` means no change is planned for a retained `wont_fix` decision.

## Build planning and rendering

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-06 | open | low | small | Correctness: RSS breaks same-date ties in the opposite order to index and tag listings. | `pipeline.py:1677-1683,1720-1729` keep and sort the highest `seq` (last discovered) first; listings use a stable descending sort (`pipeline.py:599`). Reproduced with three articles sharing a date-only `<date>`, `rss_items=2`, `per_page=2`: feed lists c, b while index page 1 lists a, b. Prepared builds stream per language, so cross-language ties may differ between build modes (traced, not run). Next: use `-seq` as the heap tie-break and pin tie order for both build modes. |
| REVIEW28-07 | open | low | small | Correctness: duplicate article and tag routes fail a full build but pass filtered builds, which publish each entry twice. | Projections bypass `OutputManifest` (`pipeline.py:1633-1649,1693-1717` versus `:732-736`). Reproduced: a copied article fails a full build with `Duplicate generated cache key: article:en:first-post`, while `--only rss,sitemap,search` exits 0 with the URL twice in sitemap, feed and search; `--only index,tags` lists it twice; tag slugs `News` and `news` do the same with `--only sitemap`. Next: check article and tag route uniqueness during projection regardless of `--only`. |
| REVIEW28-09 | open | low | medium | Correctness: `html5_void_ends` removes text that the HTML5 tokenizer treats as script data or ordinary content. | `html_serialization.py:16,83-93`; the module docstring says raw text is retained. Reproduced against html5lib 1.1: after `<!--` and a nested `<script` inside a script, a `</source>` in the remaining script text is deleted; `</source "><p>kept?</p> "x>tail` returns `tail` because `_END_TOKEN` opens quotes without a preceding `=`. Both need unusual or malformed generated markup. Next: track script-data escaped states and take the end-tag end from attribute grammar; compare with html5lib on seeded corpora. |
| REVIEW28-10 | open | low | small | Correctness: implicit HTML output inference uses Unicode whitespace where libxslt uses XML whitespace. | `backends/lxml_output.py:13-17` uses `text.strip()`. Reproduced: with no `xsl:output method` and leading U+00A0 before `<html>`, libxslt serializes XML but the engine applies the HTML projection and removes `</source>` and `</br>`, breaking well-formedness. Next: test blankness with XML whitespace only. |
| REVIEW28-11 | open | low | small | Performance/contradictions: build locks and publication snapshots are fsynced although the journal, cache and ownership are not and the docs disclaim power-loss durability. | `filesystem.py:316-320,349-350` (two locks per build from `pipeline.py:2026-2028`), `backends/publication_snapshots.py:39`; `docs/output.md:95` and `docs/generator-composition.md:472` disclaim durability. Measured: 4 fsyncs cost 15-21 ms per build, 64-67% of a no-op build of the small fixture and 5% at 1,000 articles; a publish makes 6. `flock` provides the exclusion; the payload only feeds the stale-lock warning. Next: drop the lock fsyncs and either drop the snapshot fsyncs or also sync the journal; update `tests/test_lock_release.py:44`. |
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
| REVIEW28-22 | open | low | small | Docs/observability: an invalid `<publish-at>` logs `treating as scheduled` for articles that publish immediately. | `articles.py:236-245`, called unconditionally from `:257`. Reproduced: no `<status>` plus `<publish-at>next tuesday</publish-at>` logs the warning and the page is written. `docs/articles.md` says publish-at is only used by scheduled articles. Next: parse and warn only for `scheduled`, or reword the message. |
| SCAL-01 | wont_fix | low | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | low | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| REL-02 | wont_fix | low | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |


## Cache persistence

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-25 | open | low | small | Concurrency/contradictions: retention takes other outputs' cache locks, so a disjoint build can fail with a held lock. | `cache_store.py:188-197` (`_prune_root`) versus non-blocking builder acquisition (`cache_store.py:66-75`, `pipeline.py:2027-2029`). `docs/output.md` says partitioned builds lock only their own cache file. Reproduced with an injected pause inside `_prune_root`: the other output's build raises `FileExistsError`; a retry succeeds and no data is lost. Next: document the retention lock or let builders retry briefly on their own partition lock. |
| REVIEW28-26 | blocked | medium | small | Contradictions: legacy route-metadata recovery from the cache no longer works for any real legacy ownership sidecar. | `docs/generator-composition.md:142-143` says legacy ownership can recover known metadata from its cache once; `pipeline.py:2240-2241` discards `__routes__` whenever the sidecar has no generation, and every sidecar old enough to lack `routes` also lacks `generation` (added in 5a3f0b2). Reproduced: pre-generation and version-1 sidecars fail with `Retained route metadata unavailable; run a full build`; the 7dfd2c7 tree recovered them. `tests/test_durable_routes.py:84-103` passes only because it keeps `generation`, a state no released writer produced. Fails safe. Blocked on an owner decision: keep `__routes__` as a one-time fallback when the sidecar has no generation, or delete the sentence and the dead fallback. |
| REVIEW28-27 | blocked | medium | medium | Performance/scalability: all fingerprint state is rewritten in full on every build, including a no-op, once the clock advances a second. | `output_cache.py:44`, `runtime.py:113`, `pipeline.py:2001-2002`, `ownership.py:160-177`. Measured: no-op rewrites 1.3 MB at 1,000 articles and 5.1 MB at 4,000 (0 with the clock frozen); the default shared layout rewrites all four roots (5.2 MB); a one-article edit at 4,000 writes 5.11 MB of cache plus 2.92 MB of ownership. 39% of the cache is the full article-parameter JSON per fingerprint (`pipeline.py:1068`) and 22% is `__routes__`, duplicated in ownership. Contradictions review: `docs/output.md:116-119` documents the timestamp refresh. Blocked on an owner decision on timestamp granularity or location; then store a parameter digest plus the two fields `translation_history` reads and stop duplicating routes. Keep retention expiry including `cache_retention_days: 0`. |
| REL-01 | wont_fix | low | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |


## Asset mirroring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-28 | open | low | small | Contradictions/data governance: apply-mode image optimisation leaves lock files in the asset source tree and the build publishes them. | `image_optimization.py:39`; the asset manifest (`pipeline.py:239-252`) has no exclusion. Reproduced: `assets/img/.photo.jpg.articulous.lock` is mirrored to `output/assets/img/`. `docs/generator-composition.md:574-580` calls the sibling lock intentional while `docs/building.md:144` says lock files stay outside source and output trees. Next: keep image locks outside the mirrored tree or exclude `.*.articulous.lock` from the asset manifest. |


## Native execution

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-30 | open | low | small | Reliability: the browser fence and recovery read `/proc/<pid>/stat` as UTF-8 text and fail on any host process with a non-UTF-8 name. | `backends/browser_fence.py:14`, `backends/recovery.py:23`; `backends/processes.py:29-42` reads bytes. Reproduced with a child whose comm contains byte 0xE9: `process_identity`, `owned_members` and `recovery.process_state` raise `UnicodeDecodeError`, so `stopBrowser` rejects and the profile is retained. Next: read bytes as the supervisor does. Recheck 2026-11-21: commit 1079cdf pre-filters `owned_members` with `os.getpgid`, so unrelated host processes no longer reach the text read; `process_identity` for a group member and `recovery.process_state` still raise `UnicodeDecodeError`. |
| REVIEW28-31 | open | low | small | Correctness: the ImageMagick adapter passes raw file names that ImageMagick reinterprets. | `backends/imagemagick.py:15,23-27`, `image_optimization.py:55`. Reproduced: `50%discount.jpg` aborts the whole batch (`%d` is read as a scene format); with root `.` a name starting with `-` is taken as an option. Fails loudly; nothing is wrongly replaced. `engines.py:493-504` guards the same class for Saxon. Next: use absolute paths and a fixed sanitised scratch name; fuzz file names with valid boundary names kept working. |
| REVIEW28-32 | open | low | small | Inconsistency: a failed recovery handoff raises `NativeCleanupError` with a token for native workspaces but a plain `RuntimeError` for the ImageMagick workspace. | `backends/imagemagick.py:36-42` versus `native_workspace.py:26-33`. Reproduced: `except NativeCleanupError as e: recover_session(e.token)` misses the image path while the session reservation stays in `_RETAINED`. `tests/test_converter_cancellation.py:82-99` pins only the message. Next: add the note and re-raise the same exception as `native_workspace` does. |


## Prepared builds and publication

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-37 | open | low | small | Correctness: validator `Diagnostic.path` and accompanying warnings are dropped from `BuildError`. | `builds.py:408-410`, `build_contracts.py:19-28`; documented example at `docs/generator-composition.md:293`. Reproduced: `BuildError` carries only the joined messages; no production code reads `.path`. Next: include the path in the message or attach the diagnostics tuple to the exception. |
| REVIEW28-38 | open | low | small | Docs: `CapturedSite.articles()` orders same-date articles by language code first, not by discovery order as documented. | `docs/generator-composition.md:234-235` versus `capture_adapter.py:58-65` (merge over `sorted(self.languages)`). Reproduced with `a-fr`, `b-en`, `c-fr` sharing a date: result is B, A, C. `tests/test_capture_lifetime.py:107-120` pins a layout where both orders coincide. Next: correct the sentence or merge on a discovery sequence key. |
| REVIEW28-39 | open | low | medium | Scalability: publication materialises every route and the whole cache in memory. | `publication_adapter.py:16-40` (`route_values()` at `:31`, one `json.dumps` string at `:25`, encoded again in `backends/posix.py:154`). tracemalloc around `publish_generation`: 5.5 MB at 1,119 outputs and 21.3 MB at 4,269 (4.8-4.9 KiB per output), about 0.5 GB at 100k. Opt-in. Next: stream the cache JSON to its staged file while hashing and hand backends a route iterator; keep the `PublicationInput` mapping contract and the journal cache digest. |


## Generated-site validation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-41 | open | low | small | Correctness: `read_pages` reads directories whose name ends in `.html`. | `site_validation.py:61-62`. Reproduced: `IsADirectoryError`. `output_metrics.scan` filters with `is_file()`. Same class as REVIEW27-07. Next: filter to regular files. |
| REVIEW28-42 | open | low | small | Correctness: `output_metrics.scan` and `one_page` abort on an HTML file that has no element. | `output_metrics.py:67-69,114-117` guard only `raw.strip()`; `site_validation.py:66-70` catches `ParserError`. Reproduced with a comment-only, doctype-only and PI-only file: `ParserError Document is empty`. `docs/generator-composition.md:595` says empty HTML is valid. Next: catch `etree.ParserError` and treat the file as element-free. |
| REVIEW28-43 | open | low | small | Performance: site validation repeats target resolution for every link occurrence. | `site_validation.py:184-202,153-161,13-16`. 1,000 pages with 100 links each to 1,000 unique targets: 101,000 `is_file`, 204,000 `urljoin` and 305,049 `urlsplit` calls in 1.79-1.84 s CPU; linear in links. A memo keyed by the fragment-less resolved URL gave 2.5-2.7x with identical failures. Opt-in validator. Next: memoize target, final URL and existence per validation; keep per-link diagnostics and order, fragment carry through redirects and trailing-slash rules. |


## Sitemap generation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|


## Configuration

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-44 | open | low | small | Correctness: an unknown `--lang` value is a silent no-op that reports all pages up to date. | `cli.py:67` has no validation, while `cli.py:81-99` rejects unknown `--only` values and calls that case a bug. Reproduced with languages `en`, `fr`: `--lang en,fr` and `--lang zz` exit 0 with `Discovered 0 article(s)`. Next: reject values not in `site.languages` once configuration is loaded; fuzz invalid values with every configured language as valid boundary. |
| REVIEW28-45 | open | low | small | Correctness: an uppercase-scheme `site.base_url` is accepted but silently disables hreflang alternates and JSON-LD. | `sections.py:148-152` validates through `urlsplit`, which lowercases the scheme; `structured_data.py:6` and `translations.py:61` use case-sensitive `startswith`. Reproduced: `HTTPS://example.test` builds with 0 alternates and 0 JSON-LD blocks against 1 and 1 in lowercase. Next: normalise the scheme at admission or reject non-lowercase schemes. |
| REVIEW28-46 | open | low | small | Reliability: decoder-limit and encoding failures in `config.json` bypass the `ConfigurationError` diagnostic. | `config.py:324-328` catches only `json.JSONDecodeError`. Reproduced: 1,200-deep nesting raises `RecursionError`, invalid UTF-8 raises `UnicodeDecodeError`, a 5,000-digit integer raises `ValueError`; none names the file. Same class as AUDIT26-04/15 and REVIEW27-11/19/20. Next: also catch `ValueError` and `RecursionError` around decode and parse; fuzz with deep but valid nesting as boundary. |
| REVIEW28-47 | open | low | small | Contradictions: two grammars define a language identifier. | `config.py:172` admits `[A-Za-z0-9_-]+` and the docs cite `en_US`; `translation_jobs.py:10-11` rejects underscores and case-folded duplicates. Reproduced: configuration admits `['en','pt_BR','en_US']` and `['en','EN']`, `collect_variants` rejects both. Next: share one identifier rule. |
| REVIEW28-48 | open | low | small | Docs: the root `config.json` sample omits six documented keys. | Diff against `config.DEFAULT_CONFIG`: `sitemap.include_listings`, `robots.enabled`, `site.bare_default_language`, `site.pagination.paginate_tags`, `site.pagination.empty_index`, `urls.index_first`, all documented in `docs/configuration.md:16-19`; commits 25f7405 and 74ebcde added only their own keys. The file still loads through default merging. Next: regenerate it from the defaults or state that it is deliberately partial. |
| UNUSED-01 | wont_fix | low | — | Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `config.normalize_configuration`, with direct unit tests; keep. |


## Taxonomy authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-51 | open | low | small | Correctness: near-duplicate results depend on input order. | `taxonomy_reports.py:43-52`; `SequenceMatcher.ratio()` is not symmetric. Reproduced: `['amaterasu','amateurs']` reports 0.82 while the reversed list reports nothing. The top-k heap itself is exact. Next: score both orientations and take the maximum, or canonicalise pair order. |
| REVIEW28-52 | open | low | medium | Scalability: `missing_tags` runs every vocabulary pattern against every summary. | `taxonomy_completeness.py:37-44,62-73`. Searches are exactly 2.00 x summaries x vocabulary: 0.49 s at 1,000 x 200, 8.2 s at 4,000 x 800, 32.4 s at 8,000 x 1,600. A first-token index prototype in front of the unchanged patterns returned identical results in 0.02 to 0.42 s. Opt-in helper with no in-repo caller; not regex-backtracking analysis (REDOS-001 stays declined). Next: add the token prefilter with a full-scan fallback for non-ASCII names. |
| REVIEW28-53 | open | low | medium | Scalability: near-duplicate reporting still scores a constant fraction of all tag pairs. | Recheck 2026-11-21 of commit 1079cdf, which closed this row: the prefix index in `taxonomy_reports._indexed_positions` is exact (0 mismatches against the previous all-pairs scan over 7,050 seeded cases including thresholds 0, 1 and above 1, duplicates, empty names and 150-260 character names) but still calls `quick_ratio` for 57% of pairs on random 12-letter names (1,143,284 of 1,999,000 at 2,000 names; 0.14, 0.57, 2.43 s at 500, 1,000, 2,000), 31% on mixed lengths 3-20 and 27% on hyphenated word tags, so time still quadruples per doubling. `test_review28_53_equal_length_tags_skip_unrelated_pairs` uses names built from one unique character each, the index's best case. Opt-in report with no production caller. Next: add a realistic-alphabet scaling regression and either tighten candidate generation (for example positional or multi-token filters) or record the quadratic bound as accepted. |
| REDOS-001 | wont_fix | medium | S | Optional taxonomy matcher can retry quadratically on separator-leading names. | Security/performance review; taxonomy_completeness.py:31-44: tag `-a` produces an unanchored separator run followed by `a`; searching whitespace ending in `!` retries the run from each position. Local missing_tags cases at 1k/2k/4k characters took about 5/21/79 ms; no default build caller, only the opt-in public helper. Owner instruction 2026-10-24: stop content-focused analysis and let these findings go; no post code was executed. Declined for this pass; reconsider only on explicit owner resumption. Any future fix requires permanent failing-before/passing-after scaling/semantic controls, including literal punctuation and valid phrase boundaries. Evidence/scope: reviews/regex/README.md. |


## Browser code highlighting

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-54 | open | low | small | Correctness: `CodeBlocks.language()` resolves hints through `Object.prototype`, so one such class makes `init()` throw and leaves later blocks unmounted. | `code-blocks.js:5,10-11,28,46`; `contracts/code-blocks.d.ts` declares a string result. Reproduced in headless Chromium: `class="language-constructor"` returns a function, `Prism.util.setLanguage` throws `InvalidCharacterError`, and later blocks stay unhighlighted with no copy button; unlabelled `extend` is accepted as a language. Unrelated to REDOS-002. Next: use `Object.hasOwn` for both lookups and require an own object grammar. |
| REVIEW28-55 | open | low | small | Data governance: the Prism manifest has no provenance for the three shipped CSS files. | `third_party/prism/manifest.json:27-29`: `light.css`, `dark.css` and `toolbar.css` are under `files` but not `upstream_unmodified` or `upstream_sources`; `LICENSE` also lacks a source entry. They are byte-identical to prismjs 1.30.0 `themes/prism.css`, `themes/prism-tomorrow.css` and `plugins/toolbar/prism-toolbar.css`. Next: add them to both lists. |
| REDOS-002 | wont_fix | medium | M | Optional synchronous Prism highlighting has content-sensitive quadratic paths. | Security/performance review; code-blocks.js:30 calls highlightElement without a worker or admission bound. Packaged markup tag, Bash function and batch set-variable patterns show roughly 4x cost per doubled input in completed 1k–8k local text-only cases; no snippet was executed. Owner instruction 2026-10-24 declines further post-content/highlighting analysis and hardening. Keep disposition unless owner explicitly resumes. Future work must retain normal highlighting/copy behavior and permanent malformed-input/valid-boundary regressions, with owned cancellation if isolation is selected. Limited evidence and intentionally stopped vendor review: reviews/regex/README.md. |


## Browser search

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-56 | open | low | small | Contract inconsistency: index preparation ignores the injected `schedule` and requires `MessageChannel`. | `search-client.js:83-93` (`prepareLoaded` uses `yieldTask` and a literal 200) versus the option at `:58` and `renderMatches` at `:140`. Reproduced in Node: with a custom `schedule` and no `MessageChannel`, 200 rows work and 201 rows fail every search with `ReferenceError`; before bdcaeaa preparation was synchronous. The docs state the fixed batch of 200 but not that `schedule` is bypassed. Next: use `schedule(lifetime.signal)` in `prepareLoaded` or document it as render-only in the `.d.ts`. |


## Source editing

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-58 | open | low | small | Docs/contract: a file placed in the documented transaction `stage` path without `capture()` aborts commit with a bare `KeyError`. | `source_transactions.py:116`; `docs/generator-composition.md:603-604` exposes `stage`. Reproduced: writing `manifest.json` into `tx.stage` raises `KeyError(PosixPath('manifest.json'))`; nothing is published. Next: capture on demand in `changes()` or raise a named error. |


## Translation authoring

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-60 | open | low | small | Reliability: placeholder-only blocks are sent to the provider. | `translation_xml.py:23` tests only `encoded.text.strip()`. Reproduced: `<p><img src="a.png" alt="Alt"/></p>` sends `<z1/>` as a unit; `<li><code>x</code></li>` encodes the same way. If the model answers anything but the bare placeholder the document never gets a clean source hash (traced, not run). Next: skip units with no characters outside placeholders. |
| REVIEW28-61 | open | low | small | Observability: the translator logs a retry and sleeps two seconds after the final attempt. | `translation_client.py:64-65,71`. Reproduced with `retries=0` and a refusing endpoint: one call, a 2 s sleep and a logged `retry 1` that never happens. Next: log and sleep only when another attempt remains. |


## Local preview

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-62 | open | low | small | Reliability: the preview handler drops the connection on an over-long path component instead of returning 404. | `preview.py:53-62,101,103` catch only `ValueError` and `RuntimeError`. Reproduced: a 257-character component raises `OSError: File name too long` in `send_head` and the client sees `RemoteDisconnected`; 256 characters return the custom 404. Next: treat `OSError` from the `is_dir` and `is_file` probes as not found; fuzz lengths around the limit. |
| REVIEW28-63 | open | low | small | Incongruence: preview serves a file for a trailing-slash URL that site validation and static hosts treat as missing. | `preview.py:73-77,91-95` versus `site_validation.py:44-45`. Reproduced: `GET /page.html/` returns 200 with the file while `local_path` maps the same URL to `page.html/index.html`. Next: return not found when the route ends with `/` and the target is not a directory. |


## Verification tooling

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-65 | open | low | small | Reliability: decisions in a class body nested in a function receive no complexity score. | `complexity_python.py:84-85,67-71`. Reproduced with Lizard 1.23.0: a function whose nested class body holds a filtered comprehension and a conditional expression scores 1. `docs/development.md:129-130` says unsupported syntax fails acceptance. Latent: no such code exists today. Next: keep class-body statements in the enclosing projection or reject decision nodes there. |
| REVIEW28-66 | open | low | small | Contradictions: `--root` does not relocate the default evidence path in the complexity CLIs. | `complexity_gate.py:220-221`, `complexity_xslt.py:206-207`: baseline, manifest and sources resolve against `--root`, the default `--report` against the working directory. Reproduced from another directory: `FileNotFoundError` for `reviews/complexity/functions.json` and `xslt.json`. Fails closed; CI runs from the repository root. Next: resolve a relative `--report` against the root. |
| REVIEW28-67 | open | low | small | Performance: the complexity gate re-splits the whole source file for every function. | `complexity_python.py:121-122` (`ast.get_source_segment`), used by `complexity_gate.py:67-71`. One file with 250, 500, 1,000, 2,000 functions: 0.35, 1.35, 5.26, 21.0 s; repository `check_all`: 6.30 s versus 2.64 s with one split per file and all identities still accepted. Next: split once per file and slice by line and UTF-8 column, keeping byte-identical segments for `body_sha256`. |
| REVIEW28-68 | blocked | low | small | Contradictions/wiring gap: the XSLT complexity inventory covers only the packaged stylesheet although AGENTS.md includes tests without exemptions. | `complexity_xslt.py:22,142-143` versus `complexity_gate.py:26-30` (tests are inventoried for Python and JS) and `docs/development.md:133`. The six `tests/fixtures/site/xsl/pages/*.xsl` files are in no inventory; `article.xsl` scores 10 for `match=/article` by `measure_template` and its top-level declarations are rejected by the gate parser. `reviews/complexity/xslt.md` scopes the metric to maintained packaged XSLT. Blocked on an owner decision: bring fixture XSLT into the inventory and baseline, or record the exclusion in AGENTS.md and the complexity guide. |


## Packaged content stylesheet

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-70 | open | low | small | Correctness: every `render-code-block` `<pre>` is published with a stray `xmlns:exsl` attribute. | `content.xsl:1` declares `xmlns:exsl` without `exclude-result-prefixes`; literal `<pre>` at `:42`. Reproduced with lxml for the default and `html` methods: `<pre xmlns:exsl="http://exslt.org/common" ...>`. An including stylesheet cannot exclude it. Next: add `exclude-result-prefixes="exsl"` on the stylesheet root. |


## Documentation

| id | status | severity | effort | description | notes |
|----|--------|----------|--------|-------------|-------|
| REVIEW28-71 | open | low | small | Docs: two guides are unreachable from the documentation index. | `docs/model-projections.md` and `docs/xml-source-views.md` are absent from the `README.md:14-26` table and linked from no file under `docs/`; they also lack the back-link the other guides carry. Next: link them from the README table or the Python integration guide. |
| REVIEW28-72 | open | low | small | Contradictions: `TODO.md` does not fully follow its own legend or AGENTS.md. | The legend says effort `—` marks a retained `wont_fix`, yet REDOS-001 and REDOS-002 are `wont_fix` with efforts S and M; AGENTS.md requires a review category in each description or notes, and the eleven older `wont_fix` rows carry none. Does not reopen any decision. Next: label the rows and align the legend. |

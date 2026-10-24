# TODO

## Open items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REVIEW-009 | open | M | Wire maintained code-block and clipboard JS into repository-native behavioral and coverage tests. | Wiring gaps; reliability/correctness; contradictions. Depends on REVIEW-007 for trustworthy per-function acceptance. `tests/test_theme_resources.py` checks resource hashes and XSLT output, but no repository test executes `code-blocks.js` or `prism-copy-to-clipboard.js`; the Node gates cover search and tooling only. `docs/generator-composition.md:576,645,692` refers to native browser coverage without a local gate for these maintained modules. Resolve with permanent DOM/clipboard lifecycle, failure, stale-callback and remount tests plus >=80% native counters for every maintained function; preserve exact-hash upstream exemptions and label external/historical evidence accurately. |



## Other items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| TEST-003 | blocked | S | Complete the exact SaxonC-HE 12.10 native integration acceptance run. | Reliability/correctness; cached SaxonC-PE 12.9 supplemental validation now passes all 15 functional/security tests after SAXON-001 (6ee64b0); the unchanged pinned-version test correctly rejects PE 12.9. Evidence: reviews/saxonc. Missing prerequisite: executable SaxonC-HE 12.10 and its matching libraries. Owner explicitly chose offline cached PE 12.9 validation and declined the archive transfer on 2026-10-24; no download is authorized. Provide the pinned installation locally or explicitly resume its transfer, then run all 16 tests without changing the version or security assertions. |
| PERF-01 | wont_fix | — | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | — | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| SCAL-01 | wont_fix | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| DUP-01 | wont_fix | — | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| REL-01 | wont_fix | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |
| REL-02 | wont_fix | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |
| UNUSED-01 | wont_fix | — | Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `builds._configuration`, with direct unit tests; keep. |
| UNUSED-02 | wont_fix | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

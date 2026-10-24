# TODO

## Open items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REDOS-001 | open | S | Review Python regex consumers for denial-of-service paths. | Owner request 2026-10-24; security/reliability review. After API-001, trace literal/dynamic patterns through production callers, validate input/pattern bounds and backtracking behavior with bounded offline evidence, and record each confirmed issue with required permanent regression coverage. Completion: source-backed dispositions for the scoped Python regex surface and explicit evidence/limits; no network transfer. |
| REDOS-002 | open | M | Review maintained/browser/vendor JavaScript regex consumers for denial of service. | Owner request 2026-10-24; security/performance review. After API-001, trace user/content-controlled strings into maintained scripts and packaged Prism grammars, inspect ambiguous repetitions and synchronous browser exposure, and validate concrete candidates with funded bounded local cases. Completion: calibrated findings or source-backed control dispositions with explicit native/evidence limits; no dependency installation or transfer. |

## Other items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-01 | wont_fix | — | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | — | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| SCAL-01 | wont_fix | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| DUP-01 | wont_fix | — | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| REL-01 | wont_fix | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |
| REL-02 | wont_fix | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |
| UNUSED-01 | wont_fix | — | Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `config.normalize_configuration`, with direct unit tests; keep. |
| UNUSED-02 | wont_fix | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

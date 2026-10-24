# TODO

## Open items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| API-001 | open | M | Decouple public build lifecycle contracts from planner and storage implementations. | API review; architecture/modularity/SOLID, decoupling, contradictions: independent-contract requirement conflicts with builds.py:42-103: PreparedBuild exposes BuildCtx, OutputManifest, BuildPlan, TempWorkspace and mutable cache/state; StagedBuild exposes that concrete owner and RouteCatalog. Importing StagedBuild/Diagnostic with fcntl unavailable fails through concrete filesystem imports. Define independent opaque lifecycle/read-only validation interfaces and diagnostics/results, keep concrete ownership private behind adapters, and type public entry points against them. Depends on API-003's route interface and API-010's request schemas. Completion: independent consumer/import-boundary tests plus unchanged lifecycle/publication acceptance; preserve one state owner and explicit handle cutoff. |

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
| UNUSED-01 | wont_fix | — | Keep `deep_merge` as a shared configuration helper | Used by `config.load_or_create_config` and `builds._configuration`, with direct unit tests; keep. |
| UNUSED-02 | wont_fix | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

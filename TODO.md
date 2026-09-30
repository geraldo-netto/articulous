# TODO

## Open items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| ARCH-005 | open | L | Review publication guarantees and design native backend interfaces; implement after ARCH-004 provides validated stages. | System design/platform boundaries. Contract and POSIX 5–8 day estimate: [assessment](docs/generator-composition.md#native-publication-boundary). Decide atomic visibility, rollback, crash recovery and durability guarantees during this actionable review. `filesystem.py` atomically replaces individual files; Morpha `publish` uses two renames with exception rollback and manual crash recovery. Reuse engine locking/ownership behind adapters. Require fault-injection, contention, unsafe-target and recovery tests. Native Windows remains unsupported; macOS/Windows acceptance is unavailable here and must precede any new support claim. |

## Other items

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CONTRA-002 | blocked | S | Resolve Morpha's page-one compatibility contract before migrating its redirect assertions. | Contradictions; mirrors Morpha COMPAT-003/HOST-004. `../morpha-portal/AGENTS.md:21` forbids redirects/stubs, while `portal/routes.py:index_aliases`, `portal/build.py:build`, `xsl/pages/index.xsl` and `tests/test_index_routes.py` generate or require them. Missing decision: Morpha's owner must select engine root support (ARCH-002) or portal-only index orchestration. Then remove aliases/rules and update permanent absence/root/pagination tests together, retaining the custom-404 directive. Engine design work can proceed independently. |
| DOC-01 | deferred | S | `SiteModelCtx` `@property` members carry no docstrings (articulous/models.py:34) | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |
| PERF-01 | wont_fix | — | XSL hashed per-section, not per-item | Intentional amortisation; per-item hash would re-read XSL N times. |
| PERF-02 | wont_fix | — | In-memory XML model hashed directly, not via temp file | Intentional optimisation; documented at use site. |
| SCAL-01 | wont_fix | — | Tag grouping retains per-language article references | One traversal groups tag memberships; the memory cost is scoped to one language's tag pages. |
| CC-01 | wont_fix | — | `_stream_projections` collects multiple projections in one pass | The shared scan is intentional; helpers separate projection logic without additional article-discovery passes. |
| DUP-01 | wont_fix | — | Section builders share a planning structure | Model construction differs by section; task creation already uses common XSLT/native helpers. |
| REL-01 | wont_fix | — | `save_cache` swallows `TypeError` | Intentional: a broken cache write must never crash the build. |
| REL-02 | wont_fix | — | `_stream_projections` tally counts published pages matching CLI filters | Correct by design; "Discovered N" counts selected article pages while shared projections retain their complete inputs. |
| UNUSED-01 | wont_fix | — | `deep_merge` (articulous/config.py:57) used only by `load_or_create_config` | Internal helper with direct unit tests; keep. |
| UNUSED-02 | wont_fix | — | `build_articles_section` / `build_index_section` / `build_tags_section` (pipeline.py) are dispatched through `_add_per_lang_tasks` | Intentional test seams covered by `tests/test_pipeline.py`; keep. |
| DOC-03 | wont_fix | — | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | wont_fix | — | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

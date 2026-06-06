# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-01 | open | M | `LxmlEngine._do_transform` builds `etree.XSLT(...)` without an explicit `XSLTAccessControl` policy (articulous/engines.py:121) | Article XML parsing is XXE-hardened, but a stylesheet using `document()` may still read local/network resources through libxslt. Add a default-deny/allowlisted access policy or document XSL as trusted executable input. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-03 | open | M | `copy_assets` hashes every file under `assets_dir` before it can skip unchanged assets (articulous/pipeline.py:231-266) | Fresh scan duplicate of prior rejected PERF-style concerns, but large image/video trees still pay a full read every build. Consider mtime/size manifest or per-file incremental copy. |
| PERF-04 | open | S | `run_build` serializes the whole cache to JSON twice to detect mutations (articulous/pipeline.py:930-991) | Cheap today, but cache size grows with pages. A dirty flag or version counter would avoid full-cache stringify on large sites. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCAL-02 | open | M | Cross-language projections still keep full sitemap and search payloads in memory (articulous/pipeline.py:653-709) | RSS is bounded with a heap, but `sitemap_urls` and `search_items` scale with all filtered articles. Stream to temp/model files or chunk for very large sites. |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CONC-01 | open | M | No process-level lock protects `output_dir` and `.build-cache.json` when two builds run in the same project (articulous/pipeline.py:924-991) | In-process worker cache writes are locked, but concurrent CLI invocations can race on output deletion/copy and cache save. Add a project build lock. |

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DG-01 | open | M | Every parsed article is projected into RSS, sitemap, and search with no article-level publish/exclude controls (articulous/pipeline.py:702-709) | Sites cannot mark drafts/private pages as excluded from search/sitemap/RSS once they live under `content_dir`. Add explicit metadata before users depend on directory conventions. |

## system design

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SD-01 | open | M | Section definitions are spread across config defaults, engine XSL maps, CLI help/validation, model builders, and pipeline dispatch (articulous/config.py:14-42; articulous/engines.py:24-31; articulous/pipeline.py:475-650) | Adding a section requires coordinated edits in several modules. A small section registry could centralize names, URL keys, XSL filenames, and builder wiring. |

## code duplication

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DUP-03 | open | S | Section builders repeat the same XSL hash, `_make_xslt_task`, cached-skip, and task-list shape (articulous/pipeline.py:475-632) | Fresh scan duplicate of prior rejected DUP-01. Still not urgent, but extracting only the shared task assembly may pay off if a new section is added. |

## architecture/modularity/SOLID

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| ARCH-01 | open | M | URL pattern handling is split between `build_rel_path_from_pattern` and per-model direct `Path(pattern.lstrip('/'))` exceptions (articulous/models.py:97-100; articulous/models.py:188-220) | Route shape knowledge leaks into each model builder. A typed URL/output-path strategy would clarify which patterns are page directories versus direct files. |

## decoupling

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DEC-01 | open | S | `cli.py` imports `SECTION_NAMES` from the build pipeline just to validate `--only` (articulous/cli.py:12; articulous/pipeline.py:650) | CLI validation is coupled to pipeline internals. Move section names to a neutral registry/module if the section model grows. |

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DDD-01 | open | M | Article publication policy is implicit in filesystem presence instead of a domain concept (articulous/articles.py:115-174; articulous/pipeline.py:662-709) | This overlaps DG-01 from the domain angle. A `PublicationState`/visibility concept would make draft, scheduled, hidden, and indexed states explicit. |

## reliability/correctness

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REL-01 | open | M | Output and cache writes are non-atomic (`write_text` direct to final paths) (articulous/engines.py:126; articulous/runtime.py:92) | A crash or disk-full event can leave partial generated files or cache JSON. Write to a temp file in the same directory, then replace atomically. |
| REL-02 | open | S | Invalid JSON config falls back to defaults and continues (articulous/config.py:82-86) | Useful for first run, risky for existing projects: a malformed config can silently build with `example.com` defaults. Consider fail-fast once the config file exists. |
| REL-03 | open | S | Directory-style URL conversion always appends `index.html` for article/index/tag patterns (articulous/models.py:97-100) | If a user configures `/feed.xml` or `/foo.html` for one of those patterns, output becomes `feed.xml/index.html`. Validate allowed pattern shapes per section. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-03 | open | S | Invalid/skipped articles are logged one-by-one but no final skipped count is reported (articulous/articles.py:115-174; articulous/pipeline.py:725-740) | Large sites can miss many warnings in noisy logs. Add parse/skip counters to the build summary. |

## wiring gaps

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| WIRE-01 | open | S | README advertises SaxonC as “auto-detected when null”, but `configure_saxonc` simply falls back when `saxonc.home` is missing (README.md:162; articulous/engines.py:190-198) | Either implement PATH/env discovery or adjust docs/config wording. Current production dispatcher never auto-discovers. |

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| UNUSED-03 | open | S | `write_json` is public-shaped but only used by tests, not production code (articulous/runtime.py:34-39) | Decision: delete if no planned caller, or inline into first real caller. Keeping it as a public runtime helper currently adds API surface without use. |

---

## Open — parked

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-01 | parked | S | `_stream_projections` (pipeline.py:641) emits no per-section progress; only final tally logs at pipeline.py:697 | Deliberate to keep production logs quiet; revisit if very large sites need progress feedback. |
| OBS-02 | parked | S | `timed()` (runtime.py:126) wraps tasks at DEBUG only; production builds see no per-task signal | Same trade-off as OBS-01; bumping to INFO would flood logs for normal builds. |
| DOC-01 | parked | S | `SiteModelCtx` `@property` members (models.py:33-45) carry no docstrings | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |

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
| DOC-03 | private helpers `_passes_cli_filters` / `_sorted_lang_articles` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-02 | open | M | SaxonC transforms run without an equivalent to lxml's default-deny `XSLTAccessControl` (articulous/engines.py:167-197) | If a project enables `saxonc`, stylesheets can still use processor-supported file/network access such as `document()`. Add SaxonC flags/config to disable external resource access or document Saxon XSL as trusted executable input. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-05 | open | M | Any asset manifest change recopies the entire `assets_dir` tree (articulous/pipeline.py:249-286) | Metadata checks avoid full hashing, but a single changed image still deletes and copies all assets. Copy/delete per manifest delta for large asset trees. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCAL-03 | open | M | Per-language sections retain every buildable `Article` in `articles_by_lang`/`listings_by_lang` before task planning (articulous/pipeline.py:812-888) | Cross-language projections are file-backed now, but article/index/tag builds still hold all per-language article objects. Consider per-language spill files or sorted chunking for very large sites. |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CONC-02 | open | S | Build lock files are never recovered when a prior process crashes (articulous/runtime.py:172-181; articulous/pipeline.py:1011-1012) | `O_EXCL` prevents concurrent builds, but a stale `.build-cache.lock` blocks future builds forever. Store pid/mtime and add stale-lock detection or a clear diagnostic. |

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CC-02 | open | M | Temp-file lifecycle for streamed models is split across `FragmentSink`, `SearchSink`, `BuildCtx.temp_files`, and two cleanup helpers (articulous/pipeline.py:424-499; articulous/pipeline.py:1108-1119) | Function complexity is within the limit, but the resource ownership path is hard to reason about. A context-managed model workspace would make close/unlink responsibilities explicit. |

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DG-02 | open | S | Unknown article `<status>` values are logged and treated as `published` (articulous/articles.py:115-121) | A typo such as `privte` exposes the article everywhere. Prefer fail-closed behavior (`draft`/skip) or a hard parse error for unknown publication states. |

## system design

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SD-02 | open | M | Frozen `BuildCtx` carries mutable build scratch state via `temp_files` (articulous/pipeline.py:66-104; articulous/pipeline.py:714-743) | The context mixes immutable configuration with per-run cleanup bookkeeping. Move transient files into a build/session object to preserve the typed config boundary. |

## code duplication

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DUP-04 | open | S | Cross-language builders repeat XSL hash, `_make_xslt_task`, cache-key, engine, and skip handling (articulous/pipeline.py:682-762) | The per-language builders got shared helpers, but RSS/sitemap/search still duplicate the same task assembly shape. Extract a cross-section task helper if another cross-language section is added. |

## architecture/modularity/SOLID

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| ARCH-02 | open | S | `LxmlEngine._do_transform` imports `write_text_atomic` from runtime inside the method (articulous/engines.py:137-140) | The local import avoids a top-level cycle, but it hides a cross-layer dependency from engines back into runtime. Move atomic file writing to a neutral filesystem helper module. |

## decoupling

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DEC-02 | open | S | CLI `--only` help hardcodes section names while validation reads `SECTION_NAMES` (articulous/cli.py:28-33; articulous/sections.py:30) | Adding/removing a section can leave help text stale even though validation is centralized. Generate the help list from the registry. |

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DDD-02 | open | M | Publication state is modeled as a boolean capability matrix with no transition/date semantics (articulous/articles.py:25-37; articulous/pipeline.py:812-841) | `date` is content metadata, not a publish window. If scheduled posts matter, introduce an explicit publication value object instead of adding more booleans. |

## reliability/correctness

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REL-04 | open | S | Malformed URL patterns with missing placeholders raise raw formatting errors during context/model construction (articulous/sections.py:39-57; articulous/pipeline.py:153-156) | A config like `/{language}/...` surfaces as `KeyError` instead of a targeted config validation message. Validate allowed placeholders per URL key. |
| REL-05 | open | S | Missing default config writes use direct `Path.write_text` instead of atomic write (articulous/config.py:69-74) | Runtime/cache/output writes are atomic, but first-run config creation can still leave a partial `config.json` on crash or disk-full. Reuse the atomic text helper after resolving the module boundary. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-04 | open | S | Build summary reports unpublished skips as one aggregate count (articulous/pipeline.py:983-991) | Operators cannot tell whether skipped content was `draft`, `private`, or another policy state without reading per-file logs. Track skip counts by publication state. |

## wiring gaps

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| UNUSED-03 | open | S | `write_json` is public-shaped but only used by tests, not production code (articulous/runtime.py:50-54) | Decision: delete if no planned caller, or inline into first real caller. Keeping it as a public runtime helper currently adds API surface without use. |
| UNUSED-04 | open | S | `build_rel_path_from_pattern` is a public-shaped compatibility wrapper with one production caller (articulous/models.py:98-100; articulous/pipeline.py:614-616) | Decision: inline the section-aware `build_output_path_from_pattern("articles", ...)` call unless this wrapper is intended as public API. |

---

## Open — parked

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-01 | parked | S | `_stream_projections` emits no per-section progress; only final tally/plan logs are emitted (articulous/pipeline.py:800-828; articulous/pipeline.py:859-872) | Deliberate to keep production logs quiet; revisit if very large sites need progress feedback. |
| OBS-02 | parked | S | `timed()` wraps tasks at DEBUG only; production builds see no per-task signal (articulous/runtime.py:187-194) | Same trade-off as OBS-01; bumping to INFO would flood logs for normal builds. |
| DOC-01 | parked | S | `SiteModelCtx` `@property` members carry no docstrings (articulous/models.py:24-48) | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |

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

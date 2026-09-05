# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-01 | open | M | Asset discovery follows source symlinks, so a link inside `assets/` can copy any readable file outside the project into the published output (`articulous/pipeline.py:182-190`, `articulous/pipeline.py:263-269`) | Reproduced with `assets/linked.txt -> /path/outside`: the target contents were copied as `output/assets/linked.txt`. Reject symlinks or define and enforce a root-confined link policy before hashing/copying. |
| SEC-02 | open | M | Asset writes follow pre-existing destination symlink components and can overwrite files outside `output_dir` (`articulous/pipeline.py:263-269`, `articulous/pipeline.py:288-308`) | Reproduced with `output/assets/nested -> outside/`: copying `assets/nested/payload.txt` wrote `outside/payload.txt`. Validate every destination component without following links, or stage and atomically replace a symlink-free asset tree. |
| SEC-07 | open | M | SaxonC receives original article XML and only `-ext:off`/`-xi:off`; external document reads and external DTD/entity access have no explicit restriction (`articulous/engines.py:253-287`, `articulous/pipeline.py:757-758`) | Source/documentation inference; no `Transform` binary was available for runtime reproduction. [Saxon configuration documentation](https://www.saxonica.com/html/documentation12/configuration/config-features.html) separates external-function controls from resource-protocol restrictions. Apply a confined resource policy and disable external entity loading before enabling this backend for untrusted input. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-03 | open | M | Section-limited builds still spool and sort data for unrequested sections because collection switches cover whole section groups (`articulous/pipeline.py:986-1005`, `articulous/pipeline.py:1016-1040`, `articulous/pipeline.py:1107-1112`, `articulous/pipeline.py:1138-1146`) | Reproduced `--only rss` populating sitemap and search sinks, and `--only articles` retaining listing articles that are then sorted. Pass requested-section needs into projection and sorting so only consumed stores, sinks, and RSS heap entries are produced. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCAL-02 | open | M | Index planning and execution materialize all page models, XML task payloads, and futures despite disk-backed article storage (`articulous/models.py:129-150`, `articulous/pipeline.py:773-793`, `articulous/pipeline.py:1177-1187`, `articulous/runtime.py:198-202`) | Reproduced `build_index_models` retaining all 20,000 input items across its returned page list. Yield page models/tasks incrementally and bound in-flight work to prevent peak memory growing with every page payload and queued future. |
| SCAL-03 | open | M | External article sorting merges every chunk at once, opening one descriptor per chunk without a fan-in limit (`articulous/pipeline.py:462-469`, `articulous/pipeline.py:508-518`, `articulous/pipeline.py:543-546`) | Reproduced merging 80 chunks under a 64-descriptor soft limit: `Too many open files` before the first article. Use bounded multi-pass merging or another strategy that caps simultaneously open chunk files. |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DATA-01 | open | M | Changing an output path under an existing cache key permanently orphans the old file in both full and partial builds: pruning compares keys only, then the manifest forgets the old path (`articulous/pipeline.py:1288-1313`) | Reproduced with a full build after changing the article URL from `/en/articles/hello/` to `/en/posts/hello/`: both files remain. Retain superseded paths until safely pruned, including paths changed by partial builds. |
| DATA-03 | open | M | Targeted builds leave previously published pages online after their status becomes private, draft, or future-scheduled because every CLI filter disables pruning (`articulous/pipeline.py:998-1000`, `articulous/pipeline.py:1202-1206`, `articulous/pipeline.py:1257-1258`) | High; reproduced publishing `hello`, changing it to private, then building `--only articles --slug hello`: the public HTML remains. Reconcile retired outputs within the selected scope while preserving unselected pages. |

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
| REL-10 | open | M | CI tests only Python 3.12 despite declaring Python 3.11+ support (`.github/workflows/main.yml:18-21`; `pyproject.toml:6`) | Run a supported-version matrix so CI exercises the full package contract. |
| REL-12 | open | M | Stale-key pruning can delete a newly generated page when a removed key's old path is reused by a current key (`articulous/pipeline.py:1294-1303`) | High; reproduced by removing article `1` with article pattern `/{lang}/{slug}/` and moving index pages to `/{lang}/{page}/`: the successful build deletes its new `en/1/index.html`. Protect every current manifest path before deleting stale paths. |
| REL-15 | open | S | `--dry-run` creates the output directory unconditionally (`articulous/pipeline.py:1343-1344`) | Reproduced on a fresh temporary site: `output/` exists after dry-run. Guard output-directory creation with the dry-run flag. |
| REL-19 | open | M | Generated-page ownership excludes mirrored assets, allowing a page and asset to silently overwrite each other (`articulous/pipeline.py:263-269`, `articulous/pipeline.py:525-540`, `articulous/pipeline.py:1343-1349`) | High; with article pattern `/assets/{lang}/{slug}/` and matching asset HTML, the first build emits `PAGE`; the unchanged second build restores `ASSET` and skips the page transform. Validate asset/page ownership together before writes, including ancestor path conflicts. |
| REL-20 | open | M | Stylesheet dependency hashing treats include/import hrefs as raw filesystem paths rather than XML URI references (`articulous/engines.py:77-91`) | Reproduced an include of `common%20file.xsl`: lxml compiles the valid stylesheet, but `stylesheet_hash` raises `FileNotFoundError`. Resolve dependencies consistently with the XML engine, including URI decoding and XML base URIs, while retaining the local-file access policy. |
| DOC-04 | open | S | README engine guidance contradicts production selection: the configuration table omits `native`, and development notes claim missing Saxon forces lxml for every section (`README.md:175`, `README.md:240-241`, `articulous/engines.py:339-343`) | Document `native` for sitemap/search and limit fallback wording to sections explicitly configured with `saxonc`. Native sections remain native regardless of Saxon availability. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-03 | open | S | A configured nested log path fails unless its parent already exists (`articulous/cli.py:117-130`) | Reproduced with `logging.file="logs/build.log"` as `FileNotFoundError`. Create the validated parent directory before constructing `FileHandler`. |
| OBS-04 | open | S | Reconfiguring logging removes old handlers without closing them (`articulous/cli.py:120-133`) | The removed `FileHandler` stream remained open after a second `setup_logging` call, contradicting the function's idempotence claim. Close each handler after removal. |

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
| OBS-01 | parked | S | `_stream_projections` emits no per-section progress; only final tally/plan logs are emitted (articulous/pipeline.py:838-874; articulous/pipeline.py:923-941) | Deliberate to keep production logs quiet; revisit if very large sites need progress feedback. |
| OBS-02 | parked | S | `timed()` wraps tasks at DEBUG only; production builds see no per-task signal (articulous/runtime.py:144-152) | Same trade-off as OBS-01; bumping to INFO would flood logs for normal builds. |
| DOC-01 | parked | S | `SiteModelCtx` `@property` members carry no docstrings (articulous/models.py:25-47) | Protocol members read as self-documenting from the type annotations; revisit only if external API consumers complain. |

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
| DOC-03 | private helpers `_passes_cli_filters` / `_add_per_lang_tasks` (pipeline.py) carry no docstrings | Per AGENTS.md "default to no comments"; helpers are short and self-named. Skip. |
| DUP-02 | `_collect_cross_lang_plan` body repeats `if want(...): plan[...] = build_X_section(...)` | Each branch's call signature differs (rss_articles vs sitemap_urls vs search_items); table-driving would obscure not clarify. Same rationale as DUP-01. |

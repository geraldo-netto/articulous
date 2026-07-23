# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to repository paths.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-01 | open | M | Asset discovery follows source symlinks, so a link inside `assets/` can copy any readable file outside the project into the published output (`articulous/pipeline.py:250-259`, `articulous/pipeline.py:283-294`) | Reproduced with `assets/linked.txt -> /path/outside`: the target contents were copied as `output/assets/linked.txt`. Reject symlinks or define and enforce a root-confined link policy before hashing/copying. |
| SEC-02 | open | M | Asset writes follow pre-existing destination symlink components and can overwrite files outside `output_dir` (`articulous/pipeline.py:283-294`) | Reproduced with `output/assets/nested -> outside/`: copying `assets/nested/payload.txt` wrote `outside/payload.txt`. Validate every destination component without following links, or stage and atomically replace a symlink-free asset tree. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-03 | open | M | `LxmlEngine` reparses and recompiles the same stylesheet for every output task (`articulous/engines.py:128-140`; `articulous/pipeline.py:680-682`) | A site with N article pages performs N identical XSLT compilations. Cache compiled transforms per thread and stylesheet fingerprint so parallel execution remains safe. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCAL-02 | open | S | Duplicate-output detection linearly scans the whole manifest for every planned output, making planning O(N²) (`articulous/pipeline.py:597-622`) | Maintain a reverse `relpath -> cache_key` map/set alongside the forward manifest. |
| SCAL-03 | open | M | Each paginated index slice restarts the external merge from article zero, so index construction rereads earlier chunks and trends to O(A × pages) (`articulous/models.py:128-142`; `articulous/pipeline.py:494-509`) | Paginate a single merged iterator once, or implement range-aware chunk reads that do not replay prior pages. |
| SCAL-04 | open | L | Stream sinks move sitemap/search projections to disk, but each generated model is parsed back into one full lxml DOM; search also stores both JSON and item XML (`articulous/pipeline.py:568-590`; `articulous/engines.py:131-140`) | Peak memory still grows with the complete global model. Use streaming serializers for these output formats or an engine path that supports bounded-memory transforms. |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CONC-01 | open | S | `lock_file` unlinks the lock pathname before releasing its flock, allowing another process to create and lock a new inode while the first build still holds the old one (`articulous/filesystem.py:94-104`) | Reproduced deterministically with two threads. Keep a persistent lock file and release/close the flock without unlinking it. |

## code complexity

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|

## data governance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DATA-01 | open | M | A partial build that changes an output path overwrites the old manifest mapping without pruning the old file, so later full builds can no longer discover or remove that stale output (`articulous/pipeline.py:1169-1170`, `articulous/pipeline.py:1218-1225`) | Reproduced by changing the article URL pattern, running `--only articles`, then a full build: the old article remained forever. Preserve superseded paths until a full prune, or safely remove the prior path for each rebuilt key. |

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
| REL-03 | open | S | Individually valid ISO dates can mix offset-naive and offset-aware datetimes, then crash RSS heap/index sorting with `TypeError` (`articulous/articles.py:228-230`; `articulous/pipeline.py:499-501`, `articulous/pipeline.py:914-917`) | README permits both date-only and full timestamp forms. Normalize parsed dates to one timezone policy, preferably aware UTC, before comparison. |
| REL-04 | open | M | An unchanged source asset manifest skips the entire copy without verifying destination files, so deleted or modified published assets remain missing/corrupt (`articulous/pipeline.py:266-270`, `articulous/pipeline.py:326-331`) | Reproduced by deleting `output/assets/a.txt`; the next build reported assets unchanged and did not restore it. Validate destination type/content or track and check destination fingerprints. |
| REL-05 | open | S | Asset delta copy cannot handle a path changing between file and directory (`articulous/pipeline.py:283-294`) | Reproduced file-to-directory as `FileExistsError`; directory-to-file likewise conflicts. Remove the old target when its recorded type differs before creating/copying the replacement. |
| REL-06 | open | M | Transform cache fingerprints omit the engine and transitive `xsl:include`/`xsl:import` dependencies (`articulous/pipeline.py:625-669`, `articulous/pipeline.py:680-682`) | Changing an included stylesheet scheduled no rebuild and left v1 output in place; switching lxml/SaxonC can also reuse output from the other engine. Hash the complete stylesheet dependency graph plus engine identity/version/config. |
| REL-07 | open | S | `load_cache` promises an empty cache for invalid input but only catches JSON syntax errors (`articulous/runtime.py:84-97`) | Non-UTF-8 bytes raise `UnicodeDecodeError`; read/permission failures raise `OSError`. Catch and warn for all invalid/unreadable cache cases, then return `TrackedCache()`. |
| REL-08 | open | S | Dependency checks use `exists()` instead of validating directory/file types (`articulous/engines.py:282-302`) | A regular file named `content` passes and produces a silent zero-article build; a directory at an `.xsl` path fails later during hashing. Require `is_dir()` for roots and `is_file()` for stylesheets. |
| REL-10 | open | M | CI bypasses the project dependency bounds/lock and tests only Python 3.12 despite declaring Python 3.11+ support (`.github/workflows/main.yml:23-34`; `pyproject.toml:6-17`) | Install the project test extra from the lock/metadata and run a supported-version matrix so CI exercises the actual package contract reproducibly. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-03 | open | S | A configured nested log path fails unless its parent already exists (`articulous/cli.py:117-130`) | Reproduced with `logging.file="logs/build.log"` as `FileNotFoundError`. Create the validated parent directory before constructing `FileHandler`. |
| OBS-04 | open | S | Reconfiguring logging removes old handlers without closing them (`articulous/cli.py:120-133`) | The removed `FileHandler` stream remained open after a second `setup_logging` call, contradicting the function's idempotence claim. Close each handler after removal. |

## wiring gaps

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| WIRE-01 | open | S | Asset cache entries write a schema `version` that no reader checks (`articulous/pipeline.py:262-280`) | Enforce the version in `_assets_unchanged`/`_cached_asset_manifest`, or remove the dead field until a migration policy exists. |

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

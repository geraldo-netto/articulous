# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Re-scan after the architecture split — line numbers refer to the
`articulous/` package, not the old `sitegen.py` monolith.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-05 | open | S | SaxonC subprocess invoked with `f"-s:{xml_path}"` etc. A path beginning with `-` could be parsed as a flag by Saxon. Currently low risk (paths are project-controlled), but easy hardening. | Pre-resolve to abs paths; assert no leading `-` before launch. `articulous/engines.py:104-116`. |
| SEC-06 | open | S | `tests/test_generator_basic.py` calls `shutil.rmtree("output")` with no symlink check. A symlink under the project root could redirect deletion. | Use `tmp_path` fixture or `realpath` check before rmtree. `tests/test_generator_basic.py:9`. |
| SEC-07 | open | S | `apply_cli_overrides` does `(project_root / p).resolve()` on config paths. A config with `content_dir: "../../etc"` resolves outside the project root with no warning. Config is presumed-trusted, but a check tightens the trust boundary. | After resolve, assert each path is inside `project_root` (`Path.is_relative_to`). `articulous/config.py:92-94`. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-01 | open | S | `file_hash(xsl_path)` runs inside `_make_xslt_task`, so for the articles section the same XSL file is hashed once per article. Index/tags sections share an xsl per section but still re-hash for every model page. | Hash each section's XSL once before the per-item loop; pass `xsl_hash` into `_make_xslt_task` instead of re-computing. `articulous/build.py:285-286` + section builders `articulous/build.py:319-446`. |
| PERF-02 | open | M | Temp model XML is written to disk only so its hash can drive the cache, then re-read by lxml. Avoidable round-trip. | Hash the bytes in memory; feed `etree.fromstring(...)` directly to the engine. Engine API would need to accept bytes as well as a path. `articulous/build.py:298-312`. |
| PERF-03 | open | M | `load_articles` parses every XML file serially on the main thread. Large content trees pay the full cost before the parallel pool kicks in. | Hand the per-file `parse_article_xml` calls to `run_parallel_tasks` (or `ThreadPoolExecutor.map`). `articulous/articles.py:82-90`. |
| PERF-04 | open | S | `save_cache` rewrites the full cache JSON every build, even when no section needed rebuilding. | Track whether any worker actually mutated the cache; skip the write when it is unchanged. `articulous/build.py:75-81`, `541-542`. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCA-01 | open | M | All articles are held in RAM as plain dicts. Fine today; a 100k-article site would bloat. Park until a concrete need. | Streaming iterator over `content_dir`; sort lazily by chunk. `articulous/articles.py`. |
| SCA-02 | open | M | `ThreadPoolExecutor` is used uniformly. SaxonC tasks shell out to subprocesses, so a `ProcessPoolExecutor` (or async) would avoid stacking threads that mostly wait. | Pick the executor based on whether any section uses SaxonCEngine. `articulous/build.py:104-136`. |

## concurrency

_(all open items resolved; tracked via git history)_

## code complexity

_(all open items resolved; tracked via git history)_

## code duplication

_(all open items resolved; tracked via git history)_

## architecture/modularity/SOLID

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| ARC-04 | open | M | `articulous/build.py` is 546 lines and bundles three concerns: cache + parallel runner (runtime), BuildCtx + helpers (context), and section builders + dispatch + `run_build` (pipeline). Each is independently testable. | Split into `articulous/runtime.py` (cache, file_hash, parallel) and `articulous/pipeline.py` (BuildCtx, section builders, run_build). |
| ARC-05 | open | S | `models.py` references `BuildCtx` via `TYPE_CHECKING` so the model layer leaks a back-edge into the build layer. Cosmetic but it blocks reusing models from a future non-pipeline caller. | Pass narrow params (`base_url`, `per_page`, `url_patterns`, `languages`) to model builders, or define a `SiteModelCtx` Protocol in models.py. `articulous/models.py:16-22`. |

## decoupling

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DCP-03 | open | S | `run_build` still reads `config["paths"]["content_dir"]`, `config["build"]["parallelism"]`, and `_cache_path_for` reads `config["build"]["cache_file"]`. BuildCtx already exists; these are the last config-dict reaches in the pipeline. | Add `content_dir`, `parallelism`, `cache_file` to `BuildCtx`; populate in `build_ctx_from_config`. `articulous/build.py:501-545`. |

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PAT-01 | open | M | `article` is still an untyped dict threaded through every layer. `url` is mutated onto each article inside `build_articles_section`. Hard to spot what fields exist where. | `@dataclass Article` with explicit fields (title, slug, lang, date, datetime, description, tags, source_path, url). | 
| PAT-02 | open | S | Model dicts (`{lang, page, total_pages, articles, output_path, url}` etc.) are repeated by hand in every model builder. | Dataclasses or `TypedDict` per page kind (`IndexPage`, `TagPage`, `RssFeed`, `Sitemap`, `SearchIndex`). |

## reliability/correctness

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REL-09 | open | M | `build_articles_section` mutates `art["url"]` as it runs; `build_rss_section`, `build_sitemap_section`, and `build_search_section` then read that field. Running with `--only rss` (or `--only sitemap` / `--only search`) skips the articles section, leaving `art["url"]` unset and causing `KeyError` inside the model/XML helpers. | Compute and attach `url` to each article when it is loaded (or in `build_ctx_from_config`), not as a side-effect of the articles section builder. Tied to [[PAT-01]]. `articulous/build.py:319-347` + `407-463`. |
| REL-10 | open | S | `_collect_tasks` iterates `SECTION_BUILDERS` in dict-insertion order, and that order is load-bearing because of [[REL-09]]: articles must run before any section that reads `art["url"]`. Nothing in the code documents or enforces it. | Either remove the ordering dependency (fix REL-09) or assert it explicitly in `_collect_tasks`. `articulous/build.py:490-498`. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-01 | open | S | `run_build` logs "Running N tasks in parallel..." and "Build complete." but no per-section counts (built / skipped / failed). Operators have nothing to grep on for a fast health check. | After `run_parallel_tasks`, log totals per section using the returned task results / cache deltas. `articulous/build.py:535-546`. |
| OBS-02 | open | S | No timing metrics. Slow XSL is invisible. | Wrap each task with `time.perf_counter`; log durations at DEBUG, aggregate per section at INFO. `articulous/build.py:269-312`. |

## wiring gaps

_(all open items resolved; tracked via git history)_

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DEAD-02 | open | S | `TransformEngine.name` is a `ClassVar[str]` referenced only by the dry-run debug log. Useful for tooling but otherwise marginal. Decision: keep — it doubles as the registry key in [[ARC-02]]'s strategy registry and is cheap. | `articulous/engines.py:54-69`. |
| DEAD-03 | open | S | `articles.discover_article_files` is public-shaped (no leading `_`) but only called from `load_articles` in the same module. No production caller pulls it directly. Decision: rename to `_discover_article_files` or leave for test introspection. | `articulous/articles.py:77-79`. |

---

## Open — parked

_(none yet)_

## Audit picks deliberately rejected

_(none yet)_

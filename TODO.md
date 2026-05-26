# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to the `articulous/` package.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-05 | open | S | SaxonC subprocess invoked with `f"-s:{xml_path}"` etc. A path beginning with `-` could be parsed as a flag by Saxon. Currently low risk (paths are project-controlled), but easy hardening. | Pre-resolve to abs paths; assert no leading `-` before launch. `articulous/engines.py:104-116`. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-01 | open | S | `file_hash(xsl_path)` runs inside `_make_xslt_task`, so for the articles section the same XSL file is hashed once per article. Index/tags sections share an xsl per section but still re-hash for every model page. | Hash each section's XSL once before the per-item loop; pass `xsl_hash` into `_make_xslt_task` instead of re-computing. `articulous/pipeline.py` `_make_xslt_task` + section builders. |
| PERF-02 | open | M | Temp model XML is written to disk only so its hash can drive the cache, then re-read by lxml. Avoidable round-trip. | Hash the bytes in memory; feed `etree.fromstring(...)` directly to the engine. Engine API would need to accept bytes as well as a path. `articulous/pipeline.py` `_make_xslt_task_with_temp`. |
| PERF-03 | open | M | `load_articles` parses every XML file serially on the main thread. Large content trees pay the full cost before the parallel pool kicks in. | Hand the per-file `parse_article_xml` calls to `run_parallel_tasks` (or `ThreadPoolExecutor.map`). `articulous/articles.py:82-90`. |
| PERF-04 | open | S | `save_cache` rewrites the full cache JSON every build, even when no section needed rebuilding. | Track whether any worker actually mutated the cache; skip the write when it is unchanged. `articulous/runtime.py:75-81` + `articulous/pipeline.py` `run_build`. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCA-01 | open | M | All articles are held in RAM as plain dicts. Fine today; a 100k-article site would bloat. Park until a concrete need. | Streaming iterator over `content_dir`; sort lazily by chunk. `articulous/articles.py`. |
| SCA-02 | open | M | `ThreadPoolExecutor` is used uniformly. SaxonC tasks shell out to subprocesses, so a `ProcessPoolExecutor` (or async) would avoid stacking threads that mostly wait. | Pick the executor based on whether any section uses SaxonCEngine. `articulous/runtime.py` `run_parallel_tasks`. |

## concurrency

_(all open items resolved; tracked via git history)_

## code complexity

_(all open items resolved; tracked via git history)_

## code duplication

_(all open items resolved; tracked via git history)_

## architecture/modularity/SOLID

_(all open items resolved; tracked via git history)_

## decoupling

_(all open items resolved; tracked via git history)_

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PAT-01 | open | M | `article` is still an untyped dict threaded through every layer. After REL-09 the `url` field is at least set up front, but every consumer still indexes by string key. | `@dataclass Article` with explicit fields (title, slug, lang, date, datetime, description, tags, source_path, url). Section / model builders switch to attribute access. |

## reliability/correctness

_(all open items resolved; tracked via git history)_

## observability

_(all open items resolved; tracked via git history)_

## wiring gaps

_(all open items resolved; tracked via git history)_

## unused functions/methods

_(all open items resolved; tracked via git history)_

---

## Open — parked

_(none yet)_

## Audit picks deliberately rejected

_(none yet)_

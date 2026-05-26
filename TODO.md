# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

Line numbers refer to the `articulous/` package.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-05 | open | S | SaxonC subprocess invoked with `f"-s:{xml_path}"` etc. A path beginning with `-` could be parsed as a flag by Saxon. Currently low risk (paths are project-controlled), but easy hardening. | Pre-resolve to abs paths; assert no leading `-` before launch. `articulous/engines.py:106-118`. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-01 | open | S | `file_hash(xsl_path)` runs inside `_make_xslt_task`, so for the articles section the same XSL file is hashed once per article. Index/tags sections share an xsl per section but still re-hash for every model page. | Hash each section's XSL once before the per-item loop; pass `xsl_hash` into `_make_xslt_task`. `articulous/pipeline.py:198-224` + section builders. |
| PERF-02 | open | M | Temp model XML is written to disk only so its hash can drive the cache, then re-read by lxml. Avoidable round-trip. | Hash the bytes in memory; feed `etree.fromstring(...)` directly. Engine API gains a bytes overload. `articulous/pipeline.py:227-241`. |
| PERF-03 | open | M | `load_articles` parses every XML file serially on the main thread. Large content trees pay the full cost before the parallel pool kicks in. | Hand `parse_article_xml` calls to `run_parallel_tasks` or `ThreadPoolExecutor.map`. `articulous/articles.py:82-90`. |
| PERF-04 | open | S | `save_cache` rewrites the full cache JSON every build, even when no section needed rebuilding. | Track whether any worker mutated the cache; skip the write when unchanged. `articulous/runtime.py:75-81` + `articulous/pipeline.py:497-498`. |
| PERF-05 | open | S | `attach_article_urls` walks the full article list right after `load_articles` walked it once. Two linear passes when one suffices. | Pass URL builder into `load_articles` (or `parse_article_xml`) so the URL is set during parse. `articulous/pipeline.py:151-165`. |
| PERF-06 | open | S | `parse_article_xml` does four separate `root.find(...)` calls (title, date, description, lang) — each is an XPath traversal. For large content trees the cost adds up. | Walk children once; populate the field by tag name in a single pass. `articulous/articles.py:45-54`. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCA-01 | open | M | All articles are held in RAM as plain dicts. Fine today; a 100k-article site would bloat. Park until a concrete need. | Streaming iterator over `content_dir`; sort lazily by chunk. `articulous/articles.py`. |
| SCA-02 | open | M | `ThreadPoolExecutor` is used uniformly. SaxonC tasks shell out to subprocesses, so a `ProcessPoolExecutor` (or async) would avoid stacking threads that mostly wait. | Pick the executor based on whether any section uses `SaxonCEngine`. `articulous/runtime.py:115-147`. |

## concurrency

_(all open items resolved; tracked via git history)_

## code complexity

_(all open items resolved; tracked via git history)_

## code duplication

_(all open items resolved; tracked via git history)_

## architecture/modularity/SOLID

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| ARC-06 | open | S | `cli.main()` does a function-local `from .pipeline import run_build`. The cycle that justified the deferred import is gone after the runtime/pipeline split — every other import in the package is at module top level. | Hoist the import to the top of `cli.py`. `articulous/cli.py:108-110`. |

## decoupling

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DCP-04 | open | S | `run_build` still passes the raw `config` dict directly to `validate_engines` and `configure_saxonc` before building the ctx. Those are the last two non-ctx readers of the config dict in the pipeline. | Fold both into `build_ctx_from_config` (validate first, then attach `saxonc_bin` resolved from `config["saxonc"]`) and have `run_build` consume only the ctx. `articulous/pipeline.py:457-459`. |

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PAT-01 | open | M | `article` is still an untyped dict threaded through every layer. After REL-09 the `url` field is at least set up front, but every consumer still indexes by string key. | `@dataclass Article` with explicit fields (title, slug, lang, date, datetime, description, tags, source_path, url). Section / model builders switch to attribute access. |

## reliability/correctness

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| REL-11 | open | S | Article `<lang>` is read verbatim from XML and propagated into URLs and filesystem paths (`build_rel_path_from_pattern` uses it as a path segment). A hostile or malformed article with `<lang>../foo</lang>` injects path components. Content is presumed-trusted, but a quick assertion tightens the boundary. | After `parse_article_xml`, assert `lang in ctx.languages` (or fall back to `default_language` with a warning). `articulous/articles.py:52` + `articulous/pipeline.py:151-165`. |

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-03 | open | S | No log of how many articles `load_articles` returned, or how many survived `_filter_articles`. Operators see the per-section task counts but cannot tell whether the input set was 5 articles or 5000. | Log article count after `load_articles` (INFO), and after `_filter_articles` when filters are active (INFO). `articulous/pipeline.py:471-473`. |

## wiring gaps

_(all open items resolved; tracked via git history)_

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DEAD-04 | open | S | `runtime.ensure_parent_dir` is public-shaped but only called by `write_json` in the same module. Either rename to `_ensure_parent_dir` or document the intended external use. | `articulous/runtime.py:26-29`. |

## documentation

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DOC-01 | open | S | `articulous/config.py` module docstring references `:mod:`articulous.build`` — that module was renamed to `pipeline` in the structure commit. Stale cross-reference. | Update to `:mod:`articulous.pipeline``. `articulous/config.py:6`. |

---

## Open — parked

_(none yet)_

## Audit picks deliberately rejected

_(none yet)_

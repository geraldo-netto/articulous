# TODO

Project review findings, grouped by category per `AGENTS.md`.

Format: `id | status | effort | description | notes`.
Statuses: `open`, `in-progress`, `blocked`, `parked`.

---

## security

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SEC-03 | open | S | `load_or_create_config` swallows JSON parse errors and silently returns defaults. Masks tampering or misconfig. | Log warning at minimum; consider hard fail. sitegen.py:173-176. |
| SEC-04 | open | S | `setup_logging` calls `getattr(logging, level_str)` with no validation. Attacker-controlled config can resolve to arbitrary `logging` module attribute (e.g. `disable`, `shutdown`). | Whitelist `{DEBUG,INFO,WARNING,ERROR,CRITICAL}`. sitegen.py:207. |
| SEC-05 | open | S | SaxonC subprocess invoked with f-string-prefixed args. If `xml_path` or `output_path` ever starts with `-`, Saxon CLI may parse as flag. Currently low risk (paths controlled), still hardening. | Pre-resolve to abs paths; assert no leading `-`; use `--` separator if supported. sitegen.py:281-291. |
| SEC-06 | open | S | `tests/test_generator_basic.py` runs `rm -rf output` with no symlink check. Hostile symlink in repo could delete arbitrary tree. | Use `shutil.rmtree(..., onerror=...)` with `realpath` check, or `tmp_path` fixture. tests/test_generator_basic.py:9. |

## performance

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PERF-01 | open | S | `file_hash(xsl_path)` recomputed inside each article loop iteration. Same XSL hashed N times per section. | Hash once before the loop. sitegen.py:759, 820, 875. |
| PERF-02 | open | M | Temp XML written to disk only to be hashed and re-parsed by lxml. Disk round-trip avoidable. | Hash in-memory bytes; pass bytes to `etree.fromstring` instead of writing temp file. sitegen.py:807-826, 862-878, 916-932, 970-984. |
| PERF-03 | open | M | `load_articles` parses every XML file serially. Big sites pay full I/O + parse cost on one thread. | Use `run_parallel_tasks` for parsing. sitegen.py:436-448. |
| PERF-04 | open | S | `save_cache` rewrites full cache JSON every build even when nothing changed. | Skip write if cache dict unchanged (diff against loaded state). sitegen.py:651-659. |

## scalability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| SCA-01 | open | M | All articles held in RAM as dicts. Large site (>100k articles) bloats memory. | Streaming iterator over content_dir if needed. Park until concrete need. |
| SCA-02 | open | M | `ThreadPoolExecutor` used for SaxonC subprocess tasks. Process-bound work better suited to `ProcessPoolExecutor` or external job queue at scale. | Engine-aware pool selection. sitegen.py:706. |

## concurrency

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| CON-01 | open | M | Cache mutated before task runs. `update_cache` called pre-submit; if transform fails, cache claims success and next build skips. | Move `update_cache` into task closure, run on success only. sitegen.py:785, 840, 895, 949, 1001, 1034. |
| CON-02 | open | S | Temp XML files (`output/temp/index-{n}.xml` etc) shared across concurrent builds of same project; no locking. | Use per-build temp dir (`tempfile.mkdtemp`). |
| CON-03 | open | S | `run_parallel_tasks` re-raises first exception inside `as_completed` loop. Pending futures keep running; their failures swallowed. | Cancel remaining or collect all errors. sitegen.py:709-714. |

## code complexity

_(all open items resolved; tracked via git history)_

## code duplication

_(all open items resolved; tracked via git history)_

## architecture/modularity/SOLID

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| ARC-01 | open | L | `sitegen.py` is 1117 lines, all modules embedded behind `# MODULE N` comments. No real separation. | Split into package: `cli.py`, `config.py`, `transform.py`, `cache.py`, `parallel.py`, `build/{articles,index,tags,rss,sitemap,search}.py`. |
| ARC-02 | open | M | Transform engines (`saxonc`, `lxml`) selected by string compare inside `run_transform`. Adding a third engine requires editing the function. | Strategy pattern: `class TransformEngine`, `LxmlEngine`, `SaxonEngine`; engine registry. sitegen.py:258-313. |
| ARC-03 | open | S | `apply_cli_overrides` both mutates `config` in place and returns it. Mixed contract. | Pick one; recommend pure return. sitegen.py:182-197. |

## decoupling

_(all open items resolved; tracked via git history)_

## business/design patterns/DDD

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| PAT-01 | open | M | `article` is an untyped dict passed everywhere. Fields added later (e.g. `url`) by mutation. | `@dataclass Article` with typed fields. |
| PAT-02 | open | S | No domain types for `Page`, `TagPage`, `IndexPage`, `RssFeed`. Templates of dicts repeated. | Dataclasses or `TypedDict`. |

## reliability/correctness

_(all open items resolved; tracked via git history)_

## observability

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| OBS-01 | open | S | No build summary at end of `run_build` (counts of built/skipped/failed per section). Operator has no quick health check. | Log totals after `run_parallel_tasks`. sitegen.py:1085-1089. |
| OBS-02 | open | S | No timing metrics per section or per task. Slow XSL invisible. | Wrap tasks with `time.perf_counter`, log durations. |
| OBS-03 | open | S | Inconsistent log levels: `load_or_create_config` errors silent, `parse_article_xml` errors at ERROR, `save_cache` failure at ERROR but build continues. | Define convention; apply uniformly. |

## wiring gaps

_(all open items resolved; tracked via git history)_

## unused functions/methods

| id | status | effort | description | notes |
|----|--------|--------|-------------|-------|
| DEAD-01 | open | S | No leading-`_` callables in `sitegen.py` are fully dead — most are wired. Re-verify after WIRE-* fixes; some may become orphans if features removed. | Decision: keep, pending wiring decisions. |

---

## Open — parked

_(none yet)_

## Audit picks deliberately rejected

_(none yet)_

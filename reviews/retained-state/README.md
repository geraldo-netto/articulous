# Incremental build memory and state writes

The fixture uses 4,000 or 12,000 total articles, distributed round-robin across
English, French and German. Each article has a short body, one of 65 tags and
one publication date. It uses the repository's site fixture, two workers, 20
articles per index page, lxml page rendering and native search and sitemap
writers. The site runs a cold build, an unchanged full build and a full build
after editing one body. All three use the shared-cache layout and the same
single output root.

The probe collects Python allocations with `tracemalloc` on the unchanged
build. The optional rename run traces a one-article title and URL change
immediately after the cold build. It samples live allocations after garbage collection at entry to
`_run_plan`. The peak spans the entire warm build, including planning and
persistence. The figures exclude native allocations, OS filesystem cache and
interpreter state allocated before tracing. Each build's byte counts record
the size of every cache, activity and ownership file atomically replaced. A
changed ownership document normally produces two replacements, first the
pending journal and then the committed document.

Run each size in a fresh Python process. To compare another checkout, run
these commands from that checkout with the absolute path to the probe.

```sh
PYTHONPATH=. python /path/to/reviews/retained-state/measure.py 4000
PYTHONPATH=. python /path/to/reviews/retained-state/measure.py 12000
PYTHONPATH=. python /path/to/reviews/retained-state/measure.py 4000 --rename
```

## Results

Linux x86-64, CPython 3.11.15, lxml 6.1.1. Each value below is one run and
uses decimal MB (1,000,000 bytes).

| Revision | Total articles | Live at render (MB) | Peak through planning (MB) | Entire warm-build peak (MB) |
|---|---:|---:|---:|---:|
| Original baseline `d9ad065` | 4,000 | 18.05 | 20.34 | 34.06 |
| Cache changes `a0f3b64` | 4,000 | 12.92 | 15.22 | 22.99 |
| Cache changes and planning-state release | 4,000 | 7.55 | 15.89 | 15.89 |
| Original baseline `d9ad065` | 12,000 | 55.47 | 62.31 | 102.02 |
| Cache changes `a0f3b64` | 12,000 | 40.09 | 46.93 | 68.95 |
| Cache changes and planning-state release | 12,000 | 21.29 | 46.38 | 46.38 |

Against `a0f3b64`, the planning-state release reduced live allocations at
render by 42% at 4,000 articles and 47% at 12,000. On the 4,000-article route
rename, live allocations fell from 12.94 to 7.20 MB. Its entire build peak
rose from 23.21 to 23.91 MB at preflight. Warm and rename peaks can occur before
obstruction checks and ownership journaling finish. Fingerprints and current
routes still grow with the output count.

### Persisted state

The tables show bytes per atomic replacement. The two edit ownership figures
are the pending and committed documents. The memory-lifetime changes preserved
the cache changes' write counts and byte sizes in these runs.

| Total articles | Revision | Unchanged build | Edited build fingerprint snapshot | Edited build ownership |
|---|---|---|---:|---:|
| 4,000 | `d9ad065` | 5,387,826 fingerprint | 5,387,826 | 1,622,477 + 1,622,506 |
| 4,000 | `a0f3b64` and planning-state release | 149 activity | 1,804,837 | 1,622,477 + 1,622,506 |
| 12,000 | `d9ad065` | 15,967,246 fingerprint | 15,967,246 | 4,770,399 + 4,770,428 |
| 12,000 | `a0f3b64` and planning-state release | 149 activity | 5,318,375 | 4,770,399 + 4,770,428 |

A separate shared-cache run used the same 1,000 input articles for each of four
output roots. It built `output0` through `output3` at UTC seconds
1,800,000,000 through 1,800,000,003, rebuilt `output3` unchanged at +10,
then changed `Body.` to `Changed.` in `content/en/0.xml` and rebuilt it at
+11. The unchanged fourth-root build wrote 5,784,882 fingerprint bytes at the
original baseline and 149 activity bytes at `a0f3b64`. The edit's fingerprint
replacement fell from 5,784,882 to 2,022,526 bytes. Both revisions wrote
447,094 and 447,123 ownership bytes on the edit.

# PERF-018 qualification

The owner explicitly authorized this narrow Articulous change and a separate
local commit on 2026-10-30. Contract and lifetime details: docs/model-projections.md.
Permanent regressions failed against the prior engine and pass after the change.
The full two-patch integration run passes 3,223 tests, with 16 existing skips
and 359 subtests. Native production line and branch coverage are 100%; each
changed production function passes the individual >=80% gate. Calibrated Lizard
1.23.0 measures every new/changed function, including tests, at complexity <=9.

The projection integration additionally reproduced rejection of streamed artifact
paths. Its permanent test now verifies those inputs bypass presentation projection
and retain existing file-based memory/cache behavior. The normal article, listing,
tag, feed and extra-page models use captured bytes. No test was weakened.

Raw native before/after logs are in Morpha's
reviews/performance-fixes-2026-10-30/engine-remaining/. The suite used installed
Python, Acorn and system build Python, with no download. Skips do not establish
platform support. No push or deployment was performed.

# BUILD-037 — reuse a parsed document for canonical references

The public page_references function projects detached PageReferences from the
independent ReferenceSource XPath-attribute protocol. read_pages uses this same
authoritative extractor. Callers can combine metadata audits and canonical link
facts under one short-lived document owner. No resolver behavior, attribute
selector, template exclusion or diagnostic policy changed.

Both new permanent tests failed against the old API and pass now. They cover
exact canonical/base/link/anchor facts, detached plain strings after document
mutation and an independent non-lxml source adapter. Existing malformed URL,
redirect, Unicode fragment and containment regressions also pass. The borrowed
DOM and native smart strings do not escape; only finite plain strings/sets are
retained in the result. No new descriptor, callback or global cache is owned.

Owner explicitly authorized this narrow Articulous patch and a separate local
commit on 2026-10-30. The approved three-patch integration suite passed 3,204
tests, with 16 existing skips and 359 subtests. Native production line and branch
coverage is 100%; individual changed-file function counters pass the 80% gate.
The skips are not support evidence. No packages or tools were downloaded.

Command: ARTICULOUS_BUILD_PYTHON=/usr/bin/python3
ARTICULOUS_ACORN=/home/netto/.npm/_npx/515228b7c8d004a2/node_modules/acorn
.venv/bin/python -m pytest. Per-function native counters and calibrated Lizard
1.23.0 complexity measurements are retained beside this note. All new/changed
functions measure <=9. Raw before/after logs are retained in Morpha's
reviews/performance-fixes-2026-10-30/engine-next/ packet. No push or deployment.

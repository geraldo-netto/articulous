# BUILD-039 — capture optional display-date metadata

Article and independent CapturedArticle records now retain display_date from the
original safe XML parse. First-element text and whitespace are preserved;
absent/empty text is an empty string. Sorting and publication retain the validated
date. The parser's slug admission was separated without changing its behavior to
keep the changed parser under the existing function-complexity limit.

Five permanent missing/empty/Unicode/duplicate/CDATA controls failed against the
old contract and pass now. Each also verifies that later source-file mutation
does not change captured text or source bytes. Records own only one additional
immutable string; no DOM or reader is retained. Existing spool, reader cutoff and
cleanup behavior is unchanged. The portal can now avoid reparsing captured XML.

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

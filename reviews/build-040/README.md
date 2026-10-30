# BUILD-040 — source-image identity excludes ordinary read access

The former generation value retained the whole os.stat_result. On the native
relatime filesystem, reading an unchanged source updated its access time and
caused require_image to reject its own fingerprint read. A permanent native
regression reproduced this before the fix; a same-bytes replacement control
continues to reject a changed inode.

The independent frozen ImageGeneration record retains device, inode, mode, link
count, uid/gid, size and nanosecond modification/change times. Only access time is
excluded. Existing content hashes, replacement/symlink guards, scratch cleanup,
atomic publication and persistent sibling-lock policy remain intact. Deferred
Morpha BUILD-024 is not changed. The record owns detached scalar values and adds
no handle, queue, callback or cache; existing lifecycle owners are unchanged.
Native evidence is scoped to this Linux filesystem, not unvalidated OS behavior.

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

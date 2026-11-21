# Output and ownership

[Documentation](../README.md#documentation)

This reference explains generated files, cache/state ownership, asset mirroring
and safe replacement. For commands after a failure, use
[building and recovery](building.md#recover-after-a-failure).

## Generated paths

Files are written to `output/` according to the configured `urls`
patterns. The `assets/` subtree is reserved for mirrored assets;
generated-page patterns cannot use it. Conflicting generated paths are
rejected before publishing. Defaults produce:

- `output/en/articles/<slug>/index.html`
- `output/en/page/<n>/index.html`
- `output/en/tags/<tag>/index.html`
- `output/assets/...` (incremental mirror of `assets/`)
- `output/rss.xml`
- `output/sitemap.xml`
- `output/search.json`

## File replacement and recovery

The CLI and `run_build` replace generated pages and feeds individually and
atomically; their whole build is not transactional. The original configured
output path is checked before resolution, including through the CLI. A live
generated target or any parent component that is a symlink is rejected. Content
writes use the original staging file descriptor; SaxonC inherits it through
`/dev/fd`. The SaxonC process group is stopped and checked before output is installed. Private
input copies remain owned for recovery if native shutdown cannot be confirmed.
Native diagnostics are emitted after supervised execution settles. A replaced
staging entry is rejected before publication. Publication and temporary-file
cleanup stay anchored to the original destination directory. A directory replacement
detected after rendering aborts publication; cleanup and permission changes
use the original directory and file descriptors.
Before publishing, the ownership file records
all previously owned and planned paths. Interrupted builds retain this
record, including old paths from failed URL changes. Retry without
`--only`, `--lang` or `--slug`: recovery forces a full rebuild and prunes
obsolete paths, then clears the recovery flag. A dry run leaves that flag
intact. Cache-write failures also retain the recovery flag, so the next
unfiltered build cannot reuse fingerprints from an older publication.
Inspect partial output before deploying after a failed build.
Existing unowned targets enter recovery ownership only after publication
replaces them; a planned target that was never replaced is preserved.

## Route changes

Route changes can replace a selected obsolete file with a directory, or a
directory of selected obsolete files with one file. Planning checks ownership
before publication; `--dry-run` reports these removals without changing output.
Retained outputs, unowned files, extra empty directories and unsafe file types
block the migration. The recovery journal is saved before removing obstructions,
so an interrupted migration can be retried or reverted with a full build.

## Asset mirror

The entire `output/assets/` subtree belongs to the asset mirror. Every build
compares its entries with the source: removed source entries and manual
additions in the destination are pruned, even after cache loss or a failed
first build. For example, deleting `assets/retired.pdf` removes its public
copy; adding `output/assets/manual.pdf` without a source copy removes it too.
Keep files you want published in the source assets directory. A missing
source assets directory removes the entire mirrored assets tree.
Destination file/directory mismatches are repaired, including the mirror
root when the source directory is empty.
Entries inside the asset source must be regular files or directories;
destination symlinks and hardlinks are rejected. Asset source opens reject
symlinks in every path component. Each asset file is copied through open
file descriptors and replaced atomically; the complete mirror is not
transactional. For predictable pruning, reserve the output tree for generated
files and avoid adding symlinks inside it.
Pruning removes stale generated symlinks themselves, preserving their
targets. A symlink in a stale path's parent directories aborts pruning.
Outside a planned route migration, if a stale owned file has become a directory,
pruning stops and preserves
the directory and its contents. Move or remove it explicitly before retrying;
page/feed ownership never authorizes recursive directory deletion.
Cached generated outputs must remain regular files. A directory, FIFO, or
device in place of a cached page/feed stops both normal and forced builds;
the entry is preserved for explicit recovery. Remove or relocate it, then
retry. A missing generated file is rebuilt automatically.

## Validation before publication

For validation before publication, use `check_build` or the
`prepare_build` → `render_prepared` → `validate_generated` Python lifecycle.
These APIs capture inputs and render a fresh isolated tree; `check_build`
leaves the published output, fingerprint cache and ownership state unchanged.
`build_site` additionally publishes a validated generation through the Linux
backend, with exception rollback and a recovery journal covering output and
build state. Its two directory renames leave a brief gap in output visibility;
it does not promise atomic whole-site visibility or power-loss durability.
Windows and macOS publication backends remain unsupported/unvalidated.
See the [composition and publication guide](generator-composition.md)
for extra pages, validator hooks, capability checks and recovery instructions.

## Cache, ownership and locks

The build cache (`.build-cache.json` by default) lives at the project
root. Only the filename component of `build.cache_file` is used. Entries
live under `__output_roots__`, keyed by resolved output directory. An unscoped
cache triggers a rebuild of selected pages in either storage layout.

With `build.partition_cache: true`, the first successful cache update
imports existing entries into a sibling directory, named
`.build-cache.json.articulous-roots` by default. Migration holds the shared
cache lock and waits until both active and retiring publication journals release the shared cache. The shared file
is cleared after the import. Later builds using the same cache filename read and
write one fingerprint file for their output. Setting `partition_cache` back
to false leaves the migrated directory active. Choose another cache filename
to use a separate store.

Incremental builds and whole-site publication record the current output's
last cache use in UTC seconds. A cache update removes other dated entries
whose inactivity reaches the updating build's `build.cache_retention_days`
(default 3, in 24-hour days). When only the clock advances, an unchanged build updates one small
`.articulous-activity-*` file beside the resolved base cache. Its timestamp is
valid for one output, fingerprint generation and checkpoint. The fingerprint
and ownership files keep their existing bytes. Builds reserve these activity
filenames. Incremental dry runs and validation-only builds leave the
cache untouched. Retention leaves inactive records with missing or invalid
activity timestamps in place. When that output is built again, selected pages
are rebuilt and the cache receives a fresh timestamp.
With partitioned storage, retention scans the inactive files and reuses
timestamps from a bounded, rebuildable index when file metadata matches.
It verifies each eligible file's header and activity under that output's cache lock
and skips outputs with a live lock or pending publication. Deleting or
corrupting the index triggers a scan of the authoritative headers. Activity
retirement is recorded before expiring a touched root. An interrupted cleanup
resumes under the cache lock after publication recovery. Replacing or deleting
the cache outside Articulous can leave small activity files for omitted roots.
Their recorded timestamps apply only to the original generation and checkpoint.

Ownership is stored beside each output tree in
`.output.articulous-ownership.json` by default, under the output lock.
Deleting, corrupting or switching the fingerprint cache preserves this
ownership history, so deleted/private pages can still be pruned.
The sidecar also preserves immutable route metadata, including canonical URLs,
language, category and sitemap eligibility. The fingerprint cache stores a SHA-256
digest of transform parameters and, for grouped articles, their translation group
and alternate links. The ownership sidecar holds the output path and route maps.
Both publication paths pair the cache
and sidecar with a generation identifier. An older or independently restored cache
triggers rendering of the selected pages. The sidecar also records published
translation groups and their reciprocal links so filtered builds can detect
changes that require rebuilding peers.

A populated output tree with a missing, obsolete or incomplete committed sidecar
stops the build. Restore the matching current sidecar from backup or build into
a new, empty output directory. A full build can recover a current interrupted build.
Use `--force` for a rebuild that keeps ownership history.

Builds targeting the same output directory share a lock beside it
(`.output.articulous.lock` by default), independent of cache filename.
Builds using the shared layout also share a cache lock
(`..build-cache.json.articulous.lock` by default). Partitioned builds lock their own cache file for the build,
allowing disjoint outputs to build concurrently. Expiry briefly locks the
partition directory and the candidate cache file to recheck its age and
remove it. Expiry skips busy candidates. A build starting during that check
waits for it to finish. A second build targeting an active output or cache
still fails immediately on contention. Lock files remain after release;
stale or malformed metadata is recovered once the OS lock is available.
Cache, log, lock and ownership paths must stay separate from configuration, source
trees, output trees and each other.
Whole-site publication reserves `.<output-name>.articulous-transaction/`
and its `-retired` sibling. State and source paths must be disjoint from both.
Configuration, cache, log, lock and ownership paths must refer to regular files
when they exist; directories, FIFOs and devices are rejected. File opens
are nonblocking and verify the opened file type before reading or writing.

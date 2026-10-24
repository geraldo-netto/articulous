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
live under `__output_roots__`, keyed by resolved output directory.
Ownership is also stored beside each output tree in
`.output.articulous-ownership.json` by default, under the output lock.
Deleting, corrupting or switching the fingerprint cache preserves this
ownership history, so deleted/private pages can still be pruned.
The sidecar also preserves immutable route metadata, including canonical URLs,
language, category and sitemap eligibility. Cached route metadata is derived;
it cannot override the ownership record.

Legacy cache manifests migrate automatically when no ownership file
exists. Flat caches bind to the output used for the first upgraded build;
target the existing output before changing directories. A populated output
tree without ownership history, or an invalid ownership file, stops the
build. Restore ownership from backup or choose an empty output tree.
Use `--force` for a rebuild that keeps ownership history.

Builds targeting the same output directory share a lock beside it
(`.output.articulous.lock` by default), independent of cache filename.
Builds sharing a cache also share a cache lock
(`..build-cache.json.articulous.lock` by default). A conflicting build
fails immediately rather than waiting. Lock files remain after release;
stale or malformed metadata is recovered once the OS lock is available.
Cache, log, lock and ownership paths must stay separate from configuration, source
trees, output trees and each other.
The `.<output-name>.articulous-transaction/` directory is reserved for whole-site
publication. State and source paths cannot be inside it or contain it.
Configuration, cache, log, lock and ownership paths must refer to regular files
when they exist; directories, FIFOs and devices are rejected. File opens
are nonblocking and verify the opened file type before reading or writing.
